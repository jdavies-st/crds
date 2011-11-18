"""This module defines Selector classes which are used to describe
which of a set of reference files is appropriate to use for a given execution
context.   Every Selector consists of two things:

1) a sequence of context variables which pull out pieces of the full runtime
context to match against selection keys.
2) a sequence "selections" from which a choice is made.

Each selection consists of:

1) a key to match context values against.
2) the value returned when the key matches.

Each Selector subclass implements a choose() method which defines how that
kind of Selector matches a context dictionary to its selections.

Presently the types of keys are unconstrained.   Values are presently either
filenames or nested Selectors.  In all cases,  the choice made at runtime is
essentially done by a tree walk through a set of nested Selectors.

A concrete example should make things clearer.   Here,  we describe which files
to use for a particular wavelength and software version:

>>> r = ClosestGeometricRatioSelector('effective_wavelength', {
...  1.2 : SWVersionDepSelector({
...                '<5': 'cref_flatfield_73.fits',
...                'default': 'cref_flatfield_123.fits',
...          }),
...  1.5 : SWVersionDepSelector({
...                '<5': 'cref_flatfield_74.fits',
...                'default': 'cref_flatfield_124.fits',
...         }),
...  5.0 : SWVersionDepSelector({
...                '<5': 'cref_flatfield_87.fits',
...                'default': 'cref_flatfield_137.fits',
...        }),
... })

ClosestGeometricRatioSelector and SWVersionDepSelector are both Selector
subclasses.  At calibration time,  we choose from among the possible reference
files based on our rules and the known context:

>>> r.choose({"effective_wavelength":1.4, "sw_version":6.0})
'cref_flatfield_124.fits'

Selectors are designed to be nestable and can describe rules of arbitrary type
and complexity.   Here we add time to the selection criteria:

>>> r = ClosestGeometricRatioSelector('effective_wavelength', {
...   1.2: ClosestTimeSelector("time", {
...            '2017-4-24': SWVersionDepSelector({
...                '<5': 'cref_flatfield_73.fits',
...                'default': 'cref_flatfield_123.fits',
...            }),
...            '2018-2-1': SWVersionDepSelector({
...                '<5': 'cref_flatfield_223.fits',
...                'default': 'cref_flatfield_222.fits',
...            }),
...            '2019-4-15': SWVersionDepSelector({
...                '<5': 'cref_flatfield_518.fits',
...                'default': 'cref_flatfield_517.fits',
...            }),
...        }),
...  1.5: ClosestTimeSelector("time", {
...            '2017-4-24': SWVersionDepSelector({
...                '<5': 'cref_flatfield_74.fits',
...                'default': 'cref_flatfield_124.fits',
...            }),
...            '2019-1-1': SWVersionDepSelector({
...                '<5': 'cref_flatfield_490.fits',
...                'default': 'cref_flatfield_489.fits',
...            }),
...        }),
...  5.0: SWVersionDepSelector({
...            '<5': 'cref_flatfield_87.fits',
...            'default': 'cref_flatfield_137.fits',
...        }),
... })

>>> r.choose({"effective_wavelength":1.6, "time":"2019-1-2", "sw_version":1.4})
'cref_flatfield_490.fits'

Note that the context variables used by some Selector's are implicit,
with ClosestTime utilizing "time" and SWVersionDep utilizing "sw_version".
"""
import datetime
import timestamp
import re
import pprint as pp

# import numpy as np

import log
from ezxml import Xml

# ==============================================================================

class MatchingError(LookupError):
    """Represents a MatchingSelector lookup which failed.
    """

class AmbiguousMatchError(LookupError):
    """Represents a MatchingSelector which matched more than one equivalent 
    choice.
    """

class MissingParameterError(LookupError):
    """A required parameter for a matching selector did not appear
    in the parameter dictionary.
    """

class BadValueError(LookupError):
    """A required parameter for a matching selector did not have
    any of the valid values.
    """

class UseAfterError(LookupError):
    """None of the dates in the RMAP precedes the processing date.
    """

# ==============================================================================

class ValidationError(ValueError):
    """Some Selector key did not match the set of legal values.
    """

class Selector(object):
    """Baseclass for CRDS file selectors defining the basic protocol
    of a Selector:

    0. At initialization time, the __init__() method of a selector is called to
    define the variable names which will be used to make a choice at runtime as
    well as the selections of filenames or nested Selectors which will be chosen
    from.

    1. At runtime, the choose() method of a selector is called to implement the
    Selector's picking algorithm over it's selections. Once the algorthim has
    made a choice, it either returns a filename, or it recursively calls the
    choose() method of a nested selector.

    2. The choose() method is called with keyword parameters needed to make the
    complete set of nested choices.   Each nested Selector only uses those 
    portions of the overall context that it requires.
    """
    def __init__(self, parameters, selections):
        assert isinstance(parameters, (list, tuple)), \
            "First parameter should be a list or tuple of header keys"
        assert isinstance(selections, dict),  \
            "Second parameter should be a dictionary { key: selection, ... }."
        self._parameters = list(parameters)
        self._selections = sorted(selections.items())
        
    def __repr__(self):
        return self.__class__.__name__ + "(" + repr(self._parameters) + ")"

    def keys(self):
        """Return the list of keys used to make selections."""
        return [s[0] for s in self._selections]

    def choices(self):
        """Return the list of items which can be selected."""
        return [s[1] for s in self._selections]

    def choose(self, header):
        """Given `header`,  operate on self.keys() to choose one of
        self.selections(). 
        """
        raise NotImplementedError("Selector is an abstract class."
                                  " A subclass must re-define choose().")

    def get_choice(self, selection, header):
        """Provide boiler-plate code to extract a choice or recurse."""
        choice = selection[1]
        if isinstance(choice, Selector):
            return choice.choose(header)
        else:
            return choice
        
    def to_xml(self):
        """Returns Xml object representing this selector."""
        selections = []
        for key, choice in self._selections:
            selections.append(self._selection_xml(key, choice))
        return Xml(self.__class__.__name__.lower(), elements=selections,
                   attributes={ "parkeys": " ".join(self._parameters)})
        
    @property
    def selection_xname(self):
        """XML element name for one selection."""
        return self.__class__.__name__[:-len("selector")].lower()

    def _selection_xml(self, key, choice):
        """XML for one selection."""
        if isinstance(choice, Selector):
            values = choice.to_xml()
        else:
            values = choice
        return Xml(self.selection_xname, elements=[values],
                   attributes={"key":str(key)})
    
    def get_parkey_map(self):
        """Return a mapping from parkeys to values for them."""
        pmap = {}
        for i, par in enumerate(self._parameters):
            wild = par.startswith("*")
            if wild:
                par = par[1:]
            if par not in pmap:
                pmap[par] = set()
            if wild:
                pmap[par].add("*")
            for choice in self.keys():
                val = choice[i]
                if val == "NOT PRESENT":
                    val = "*"
                pmap[par].add(val)
        for par, val in pmap.items():
            val = val.difference(set(["%NO REFERENCE%"]))
            pmap[par] = sorted(list(val))
        return pmap

    def reference_names(self):
        """Return the list of reference files located by this selector.
        Assume any choice that is a string is a reference file.  Recursively
        search for reference files in nested selectors.
        """ 
        files = set()
        for choice in self.choices():
            if isinstance(choice, Selector):
                new_files = choice.reference_names()
            else:
                new_files = [choice]
            for reffile in new_files:
                files.add(reffile)
        return sorted(list(files))
    
    def format(self, indent=0):
        """Recursively pretty-format the Selector tree rooted in `self` 
        indenting each line with 4*`indent` spaces.   Return the resulting
        string.
        """
        rmap_name = getattr(self, "rmap_name",  
                            self.__class__.__name__[:-len("Selector")])
        lines = [rmap_name + "({"]
        for key, sel in self._selections:  
            if isinstance(sel, Selector):
                pf_sel = sel.format(indent+1)
            else:
                pf_sel = repr(sel)
            lines.append((indent+1)*" "*4 + repr(key) + 
                         " : " + pf_sel + ",")
        lines.append(indent*4*" " + "})")
        return "\n".join(lines)
    
    def validate(self, valid_values_map, trap_exceptions=False, context=""):
        """Iterate over this Selector's keys checking each field
        of each key against `valid_values_map`.
        
        valid_values_map:    { parkey : [ legal values... ], ... }
        
        Raise a ValueError if there are any problems with
        """
        warned = []
        for key in self.keys():
            self.validate_key(key, valid_values_map, warned, trap_exceptions, context)
        for choice in self.choices():
            if isinstance(choice, Selector):
                choice.validate(valid_values_map, trap_exceptions, context)
            
    def validate_key(self, key, valid_values_map, warned, trap_exceptions, context):
        """Validate a single `key` against the possible field values
        in `valid_values_map`.   ABSTRACT STUB always passes.
        """
        if context:
            context += " : "
        try:
            self._validate_key(key, valid_values_map, warned)
        except ValidationError, exc:
            if trap_exceptions:
                log.error(context + repr(key))
            else:
                raise ValidationError(repr(key) + " " + str(exc))

    def _validate_key(self, key, valid_values_map, warned):
        """Abstract method validates a single key or raises exception."""
        pass

    def file_matches(self, filename, sofar=()):
        """Return the nested match keys leading to selections of `filename`.
        Assume the deepest value in the Selector tree must be a filename.
        """
        matches = []
        for key, value in self._selections:
            here = tuple(sofar + (self.match_item(key),))
            if isinstance(value, Selector):
                matches += value.file_matches(filename, here)
            else:
                if filename == value:
                    matches.append(here)
        return sorted(matches)
    
    def match_item(self, key):
        return tuple(zip(self._parameters, key))
    
    def difference(self, other, path):
        """Return the list of differences between `self` and `other` where 
        `path` names the
        """
        def msg(key, *args):
            p2 = path
            if key:
                p2 = p2 + (key,)
            return p2 + (" ".join(args),)
        if self.__class__ != other.__class__:
            return [msg(None, "different classes", 
                    repr(self.__class__.__name__), ":",
                    repr(other.__class__.__name__))]
        if self._parameters != other._parameters:
            return [msg(None, "different parameter lists ", 
                    repr(self._parameters), ":", 
                    repr(other._parameters))]
        differences = []
        other_keys = other.keys()
        other_map = dict(other._selections)
        for key, choice in self._selections:
            if key not in other_keys:
                differences.append(msg(key, "deleted"))
            else:
                other_choice = other_map[key]
                if isinstance(choice, Selector):
                    differences.extend(choice.difference(
                        other_choice, path + (key,)))
                elif choice != other_choice:
                    differences.append(msg(key, "replaced", repr(choice), 
                                           "with", repr(other_choice)))
        self_keys = self.keys()
        for key in other_keys:
            if key not in self_keys:
                differences.append(msg(key, "added"))
        return differences

# ==============================================================================

class Matcher(object):
    """Matches a single key of a matching tuple to a dataset value.  Every
    key of a MatchingSelector will have a tuple of corresponding Matchers.
    """
    def __init__(self, key):
        self._key = key
        
    def match(self, value):
        """Return 1 (match),  0 (don't care), or -1 (no match).
        """
        return 1 if self._key == value else -1

    def __repr__(self):
        return self.__class__.__name__ + "(%s)" % self._key
        
class RegexMatcher(Matcher):
    """
    >>> m = RegexMatcher("foo")
    >>> m.match("bar")
    -1
    >>> m.match("foo")
    1
    """
    def __init__(self, key):
        Matcher.__init__(self, key)
        if key == "*":
            key = "^.*$"
        elif isinstance(key, tuple):
            key = "|".join(["^" + k + "$" for k in key])
        else:
            key = "^" + key + "$"
        self._regex = re.compile(key)
        
    def match(self, value):
        return 1 if self._regex.match(value) else -1
        
class InequalityMatcher(Matcher):
    """
    >>> m = InequalityMatcher(">1.2")
    >>> m.match("1.3")
    1
    >>> m.match("1.2")
    -1
    >>> m.match("-100")
    -1

    >>> m = InequalityMatcher("<1.2")
    >>> m.match("1.3")
    -1
    >>> m.match("1.2")
    -1
    >>> m.match("-100")
    1
    """
    def __init__(self, key):
        Matcher.__init__(self, key)
        parts = re.match(
            "^([><]=?)\s*([-+]?[0-9]*\.?[0-9]+([eE][-+]?[0-9]+)?)", key)
        self._operator = parts.group(1)
        self._value =  float(parts.group(2))
        
    def match(self, value):
        return { 
            ">" : lambda m, n :  1 if m > n else -1,
            "<" : lambda m, n :  1 if m < n else -1,
            ">=" : lambda m, n :  1 if m >= n else -1,
            "<=" : lambda m, n :  1 if m <= n else -1,
         }[self._operator](float(value), self._value)

class WildcardMatcher(Matcher):
    """Matcher that always matches,  simplifies/speeds code elsewhere."""
    def __init__(self, key="*"):
        Matcher.__init__(self, key)
        
    def match(self, value):
        """Always match with "don't care" status."""
        return 0   

def matcher(key):
    """Factory for different matchers based on key types."""
    if isinstance(key, tuple):
        return RegexMatcher(key)
    elif key == "*":
        return WildcardMatcher(key)
    elif key.startswith((">","<")):
        return InequalityMatcher(key)
    else:
        return Matcher(key)

class MatchingSelector(Selector):
    """Matching selector does a modified dictionary lookup by directly matching
    the runtime (header) parameters specified as choose() header to the .   
    MatchingSelector differs from a simple dictionary in that some of the 
    Selector parameters may begin with '*'.   '*' means that the parameter was 
    considered optional by the HTML CDBS tables and not all selections supply 
    it.   Explicit values for *-parameters presently come from one of two 
    places:  from the CDBS table row,  or from the reference file header.   
    Literal *-values mean the parameter was not specified in the table and was 
    not specified in the reference file,  or was specified in the reference 
    file as ANY.

    What's hard is that for some selections,  the same parameter will be a 
    "do care".   This complexity arises because different usages of the same 
    instrument are parameterized differently, whereas there is only a single 
    header keyword for all usages.   In essence,  within a single instrument, 
    the same header keyword (file kind) maps onto different tables,  .e.g. for
    a different detector.

    >>> m = MatchingSelector(("*foo","bar"), {
    ...    ('1.0', '*') : "100",
    ...    ('1.0', '2.0') : "200",
    ...    ('*', '*') : "300",
    ... })

    >>> m.choose(dict(foo='1.0',bar='2.0'))
    '200'

    Since foo has a leading *,  it is optional:

    >>> m.choose(dict(bar='2.0'))
    '200'
    
    It matches 200 because bar=2.0 is weighted more than bar=*
    which also matches,  just not as strongly.

    Since bar has no leading *,  it is required:

    >>> m.choose({})
    Traceback (most recent call last):
    ...
    MissingParameterError: Required parameter 'bar' is missing.
    
    >>> print m.format()
    Match({
        ('*', '*') : '300',
        ('1.0', '*') : '100',
        ('1.0', '2.0') : '200',
    })
    
    
    All match tuple fields should appear on a valid values list:

    >>> m.validate({ "foo" : ("1.0",), "bar":("3.0",) })
    Traceback (most recent call last):
    ...
    ValidationError: ('1.0', '2.0') Field 'bar'='2.0' is not in ('3.0',)
    
    Match tuples should have the same length as the parameter list:
    
    >>> m = MatchingSelector(("*foo","bar"), { ('1.0',) : "100", })
    Traceback (most recent call last):
    ...
    ValueError: Match tuple ('1.0',) wrong length for parameter list ('foo', 'bar')

    
    The last thing matched in a selector tree is assumed to be a file:
    
    >>> m = MatchingSelector(("*foo","bar"), {
    ...    ('1.0', '*') : "100",
    ...    ('1.0', '2.0') : "200",
    ...    ('*', '*') : "300",
    ...    ('5.0', '3.0') : "200",
    ... })
    
    file_matches() returns a list of recursive trails/lists of keys which lead 
    to a given file:
    
    >>> m.file_matches("200")
    [((('foo', '1.0'), ('bar', '2.0')),), ((('foo', '5.0'), ('bar', '3.0')),)]
    
    The result of file_matches() is a list of lists of keys because it is
    used recursively on trees of mappings and selectors.
    
    """
    rmap_name = "Match"
    
    def __init__(self, parameters, selections, rmap_header=None):
        Selector.__init__(self, parameters, selections)  # largely overridden
        self._parameters = []
        self._required = {}
        self._value_map = {}
        self._selections = sorted(selections.items())

        self.setup_parameters(parameters)
        
        selections = self.fix_simple_keys(selections)
        
        if rmap_header is None:
            rmap_header = {}
        self._substitutions = rmap_header.get("substitutions", {})
        selections = self.do_substitutions(selections, self._substitutions)
        
        self._match_selections = self.get_matcher_selections(selections)
        self._value_map = self.get_value_map()
    
    def setup_parameters(self, parameters):
        """Strip off *=optional prefixes and store the status in the _required
        mapping.  Save simple *-less var names in the _parameters list.
        """
        for par in parameters:
            if par.startswith("*"):
                par = par[1:]
                self._required[par] = False
            else:
                self._required[par] = True
            self._parameters.append(par)
            
    def fix_simple_keys(self, selections):
        """ Enable simple mappings like:  "ACS":"filename" rather than 
        ("ACS",):"filename"
        """
        if len(self._parameters) != 1:
            return selections
        new_selections = {}
        for key, value in selections.items():
            if not isinstance(key, tuple):
                key = (key,)
            new_selections[key] = value
        return new_selections

    def do_substitutions(self, selections, substitutions):
        """Replace parkey values in `selections` which are specified
        in mapping `substitutions` as {parkey : { old_value : new_value }}
        """
        if substitutions is None:
            return selections
        for parkey in substitutions:
            which = self._parameters.index(parkey)
            for match in selections.keys():
                which = self._parameters.index(parkey)
                old_parvalue = match[which]
                if old_parvalue in substitutions[parkey]:
                    replacement = substitutions[parkey][old_parvalue]
                    if isinstance(replacement, list):
                        replacement = tuple(replacement)
                    new_match = list(match)
                    new_match[which] = replacement
                    new_match = tuple(new_match)
                    selections[new_match] = selections.pop(match)
        return selections


    def get_matcher_selections(self, mappings):
        """Expand the selections from the spec file to include a tuple
        of Matcher objects for each selection key.   Return new selections
        of the form:
               { spec_key_tuple :  (Matcher_tuple, choice) }
        """
        selections = {}
        for keytuple, choice in mappings.items():
            matchers = []
            for parkey in keytuple:
                matchers.append(matcher(parkey))
            selections[keytuple] = (tuple(matchers), choice)
        return selections

    def get_choice(self, selection, header):
        raise NotImplementedError("MatchingSelector isn't a uniform subclass.")

    def choose(self, header):
        """Match the specified `header` to this selector's selections and
        return the best matching choice.    This is the top-level entry point
        for runtime selection making.
        """
        self.validate_query(header)
        
        # Iterate through ranked choices from best to worst,  stopping at the
        # first/best overall nested selection.  For HST, multiple tries may be
        # needed because there is no guarantee that the nested UseAfter selector
        # will also match;  in that case,  the next best match where the
        # UseAfter selector does produce a result is desired.
        for choice in self._winnowing_match(header):
            if isinstance(choice, Selector):
                try:
                    return choice.choose(header)
                except LookupError, exc:
                    log.verbose("Nested selector failed", str(exc))
                    continue
            else:
                return choice
            
        log.verbose("Match failed.")
        raise MatchingError("No match.")

    def _winnowing_match(self, header):
        """Iterate through each of the parameters in `fitskeys`, binding
        them successively to corresponding values from `header`.  For
        each bound fitskey,  iterate through `selections` and winnow out
        keys which cannot match based on the value of the current fitskey.
        Successively yield any survivors,  in the order of most specific
        matching value (fewest *'s) to least specific matching value.
        """        
        weights, remaining = self._winnow(header, dict(self._match_selections))

        sorted_candidates = self._rank_candidates(weights, remaining)
        
        # Yield successive candidates in order from best match to worst, failing
        # if any candidate group has more than one equivalently weighted match.
        for _weight, group in sorted_candidates:
            if len(group) > 1:
                log.verbose("Ambigious match error.")
                raise AmbiguousMatchError("Ambiguous match.")
            else:
                selector = remaining[group[0]][1]
                log.verbose("Matched", repr(group), "returning", repr(selector))
                yield selector
    
    def _winnow(self, header, remaining):
        """Based on the parkey values in `header`, winnow out selections
        from `remaining` which cannot possibly match.  For each surviving
        selection,  weight each parkey which matches exactly as -1 and 
        "don't care" matches as 0.
        
        returns   ( {match_tuple:weight ...},   remaining_selections
        """
        # weights counts the # of parkey value matches, establishing a
        # goodness-of-match weighting.  negative weights are better matches
        weights = {}
        for match_tuple in remaining.keys():
            weights[match_tuple] = 0

        for i, parkey in enumerate(self._parameters):
            value = header.get(parkey, "NOT PRESENT")
            log.verbose("Binding", repr(parkey), "=", repr(value))
            for match_tuple, (matchers, _subselectors) in remaining.items():
                # Match the key to the current header vaue
                match_status = matchers[i].match(value)
                # returns 1 (match), 0 (don't care), or -1 (no match)
                if match_status == -1:
                    if self._required[parkey]:
                        del remaining[match_tuple]   # winnow!
                else: # matched or don't care,  set weights accordingly
                    weights[match_tuple] -= match_status   
        return weights, remaining

    def _rank_candidates(self, weights, remaining):
        """Rank the possible matches in `remaining` according to
        their corresponding `weights`,  with lowest values indicating
        best matches.
        
        Return  sorted( [(weight, [match_tuples...])...]
        """        
        # Create a mapping of candidate matches: { weight : [ match_tuples...] }
        candidates = {}
        for match_tuple, _junk in remaining.items():
            if weights[match_tuple] not in candidates:
                candidates[weights[match_tuple]] = []
            candidates[weights[match_tuple]].append(match_tuple)
        # Sort candidates into:  [ (weight, [match_tuples...]) ... ]
        # Lowest weight is best match
        candidates = sorted([(x[0], tuple(x[1])) for x in candidates.items()])
        if log.get_verbose():
            log.verbose("Candidates", pp.pformat(candidates))
        return candidates

    def get_value_map(self):
        """Return the map { FITSVAR : ( possible_values ) }
        """
        vmap = {}
        for i, fitsvar in enumerate(self._parameters):
            vmap[fitsvar] = set()
            for key in self.keys():
                try:
                    values = key[i]
                except IndexError:
                    raise ValueError("Match tuple " + repr(key) +
                                     " wrong length for parameter list " + 
                                     repr(tuple(self._parameters)))
                if not isinstance(values, tuple):
                    values = [values]
                for value in values:
                    vmap[fitsvar].add(value)
        for fitsvar in vmap:
            vmap[fitsvar] = tuple(sorted(vmap[fitsvar]))
        return vmap

    def validate_query(self, header):
        """Raise exceptions if `header` does not contain a required
        key,  or if the value of any key is not one of the possible
        values.
        """
        for fitsvar in self._parameters:
            if fitsvar in header:
                value = header[fitsvar]
                valid_values = self._value_map[fitsvar]
                if self._required[fitsvar] and value not in valid_values and \
                    '*' not in valid_values:
                    raise BadValueError("Key " + fitsvar + "=" + value +
                                " not in valid values " + repr(valid_values))
            else:
                if self._required[fitsvar]:
                    raise MissingParameterError(
                        "Required parameter " + repr(fitsvar) + " is missing.")

    def get_binding(self, header):
        """Return the assignment of `header` values to the parkeys of this
        Selector.
        """
        # get the parameter names that matter,  based on *dataset*
        binding = {}
        for fitsvar in self._parameters:
            if fitsvar in header:
                binding[fitsvar] = header[fitsvar]
            elif not self._required[fitsvar]:
                binding[fitsvar] = '*'
            else:
                binding[fitsvar] = '**required parameter not defined**'
        return binding

    def _validate_key(self, key, valid_values_map, warned):
        """Validate a single selections `key` against the possible field values
        in `valid_values_map`.   Note that each selections `key` is 
        (nominally) a tuple with values for multiple parkeys.
        """
        if len(key) != len(self._parameters):
            raise ValidationError("wrong length for parameter list " + 
                                  repr(self._parameters))
        for i, name in enumerate(self._parameters):
            if name.startswith("*"):
                name = name[1:]
            if name not in valid_values_map:
                if name not in warned:
                    warned.append(name)
                    log.warning("Parameter", repr(name), "is unchecked.")
                continue
                # raise ValidationError("Unknown parameter " + repr(name))
            valid = valid_values_map[name]
            value = key[i]
            if value in ["NOT PRESENT"] or value == "*":
                continue
            if value in valid:
                continue
            if value.replace(".0","") in valid:
                continue
            if not valid:  # some TPNs are type-only
                continue
            if len(valid) ==1 and ":" in valid[0]:   # handle ranges
                min, max = [float(x) for x in valid[0].split(":")]
                if min <= float(value) <= max:
                    continue
                else:
                    raise ValidationError("Field " + repr(name) + "=" + repr(key[i]) + 
                                  " is not in range [" + str(min) + " .. " + 
                                  str(max) + "]")     
            if name in self._substitutions and \
                value in self._substitutions[name]:
                continue
            raise ValidationError("Field " + repr(name) + "=" + repr(key[i]) + 
                                  " is not in " + repr(valid))
            
    def _is_substitution(self, name, value):
        """Return True iff `value` is a valid substitution in `name`."""
# ==============================================================================

class UseAfterSelector(Selector):
    """A UseAfter selector chooses the greatest time which is less than
    the "date" condition and returns the corresponding item.

    >>> u = UseAfterSelector(("DATE-OBS", "TIME-OBS"), {
    ...        '2003-09-26 01:28:00':'nal1503ij_bia.fits',
    ...        '2004-02-14 00:00:00':'o3913216j_bia.fits',
    ...        '2004-04-25 21:31:00':'o5d10135j_bia.fits',
    ...        '2004-06-18 04:36:00':'o9s16388j_bia.fits', 
    ...        '2004-07-02 08:09:00':'o9t1525sj_bia.fits',
    ...        '2004-07-14 16:52:00':'o9f15549j_bia.fits',
    ...        '2004-07-30 00:18:00':'o9t1553tj_bia.fits',
    ... })


    # exact match
    >>> u.choose({'DATE-OBS': '2004-07-02', 'TIME-OBS': '08:09:00'})   
    'o9t1525sj_bia.fits'

    # just before, in between
    >>> u.choose({'DATE-OBS': '2004-07-02', 'TIME-OBS': '08:08:59'})   
    'o9s16388j_bia.fits'

    # later than all entries
    >>> u.choose({'DATE-OBS': '2005-07-02', 'TIME-OBS': '08:08:59'}) 
    'o9t1553tj_bia.fits'

    # earlier than all entries
    >>> u.choose({'DATE-OBS': '2000-07-02', 'TIME-OBS': '08:08:59'})   
    Traceback (most recent call last):
    ...
    UseAfterError: No selection with time < '2000-07-02 08:08:59'
    
    UseAfter dates should look like YYYY-MM-DD HH:MM:SS or:
    
    >>> u = UseAfterSelector(("DATE-OBS", "TIME-OBS"), {
    ...        '2003-09-26 foo 01:28:00':'nal1503ij_bia.fits',
    ... })
    
    >>> u.validate({"DATE-OBS":"*", "TIME-OBS":"*"})
    Traceback (most recent call last):
    ...
    ValidationError: '2003-09-26 foo 01:28:00' date has invalid format.

    A more subtle error in the date or time should still be detected:

    >>> u = UseAfterSelector(("DATE-OBS", "TIME-OBS"), {
    ...        '2003-09-35 01:28:00':'nal1503ij_bia.fits',
    ... })
    >>> u.validate({"DATE-OBS":"*", "TIME-OBS":"*"})
    Traceback (most recent call last):
    ...
    ValidationError: '2003-09-35 01:28:00' date has invalid format.
    """
    def __init__(self, parameters, datemapping, rmap_header=None):
        Selector.__init__(self, parameters, datemapping)

    def choose(self, header):
        date = timestamp.reformat_date(
            " ".join([header[x] for x in self._parameters]))
        log.verbose("Matching date", date, " ")
        selection = self.bsearch(date, self._selections)
        return self.get_choice(selection, header)

    def bsearch(self, date, selections):
        """Do a binary search over a sorted selections list."""
        if len(selections) == 0:
            raise UseAfterError("No selection with time < " + repr(date))
        elif len(selections) > 1:
            left = selections[:len(selections)//2]
            right = selections[len(selections)//2:]
            compared = right[0][0]
            log.verbose("...against", compared, eol="")
            if date >= compared:
                return self.bsearch(date, right)
            else:
                return self.bsearch(date, left)
        else:
            if date >= selections[0][0]:
                log.verbose("matched", repr(selections[0]))
                return selections[0]
            else:
                raise UseAfterError("No selection with time < " + repr(date))
            
    def _validate_key(self, key, valid_values_map, warned):
        try:
            timestamp.parse_numerical_date(key)
        except ValueError:
            raise ValidationError("date has invalid format.")
        
    def match_item(self, key):
        """Account for the slightly weird UseAfter syntax."""
        return tuple(zip(self._parameters, key.split()))
    
    def _selection_xml(self, key, choice):
        if isinstance(choice, Selector):
            return Xml(self.selection_xname, attributes = {"date":key}, 
                        elements=[choice.to_xml()], eol="")
        else:
            return Xml(self.selection_xname, attributes = {"date":key}, 
                       elements=[choice], eol="")

# ==============================================================================

class ClosestGeometricRatioSelector(Selector):
    """ClosestGeometricRatio selects the choice whose key is at the smallest
    distance from the specified condition value.

    >>> r = ClosestGeometricRatioSelector("effective_wavelength", {
    ...  1.2 : "cref_flatfield_120.fits",
    ...  1.5 : "cref_flatfield_124.fits",
    ...  5.0 : "cref_flatfield_137.fits",
    ... })

    >>> r.choose({"effective_wavelength":1.0})
    'cref_flatfield_120.fits'

    >>> r.choose({"effective_wavelength":1.2})
    'cref_flatfield_120.fits'

    >>> r.choose({"effective_wavelength":1.25})
    'cref_flatfield_120.fits'

    >>> r.choose({"effective_wavelength":1.4})
    'cref_flatfield_124.fits'

    >>> r.choose({"effective_wavelength":3.25})
    'cref_flatfield_124.fits'

    >>> r.choose({"effective_wavelength":3.26})
    'cref_flatfield_137.fits'

    >>> r.choose({"effective_wavelength":5.0})
    'cref_flatfield_137.fits'

    >>> r.choose({"effective_wavelength":5.1})
    'cref_flatfield_137.fits'
    """
    def __init__(self, keyname, selections):
        if not isinstance(keyname, str):
            raise TypeError("First parameter of ClosestGeometricRatio should be"
                            " the name of a variable to check,  i.e. an str.")
        Selector.__init__(self, [keyname], selections)

    def choose(self, header):
        import numpy as np
        keyval = float(header[self._parameters[0]])
        nkeys = np.array(self.keys(), dtype='f')
        diff = np.abs(nkeys - keyval)
        index = np.argmin(diff)
        return self.get_choice(self._selections[index], header)

# ==============================================================================

class LinearInterpolationSelector(Selector):
    """LinearInterpolation selects the the bracketing values of the
    given context variable,  returning a two-tuple.

    >>> r = LinearInterpolationSelector("effective_wavelength", {
    ...   1.2: "cref_flatfield_120.fits",
    ...   1.5: "cref_flatfield_124.fits",
    ...   5.0: "cref_flatfield_137.fits",
    ... })

    >>> r.choose({"effective_wavelength":1.25})
    ('cref_flatfield_120.fits', 'cref_flatfield_124.fits')

    Note that an exact match still produces a two-tuple.

    >>> r.choose({"effective_wavelength":1.2})
    ('cref_flatfield_120.fits', 'cref_flatfield_120.fits')

    >>> r.choose({"effective_wavelength":1.5})
    ('cref_flatfield_124.fits', 'cref_flatfield_124.fits')

    >>> r.choose({"effective_wavelength":5.0})
    ('cref_flatfield_137.fits', 'cref_flatfield_137.fits')

    Selections off either end choose the boundary value:

    >>> r.choose({"effective_wavelength":1.0})
    ('cref_flatfield_120.fits', 'cref_flatfield_120.fits')

    >>> r.choose({"effective_wavelength":6.0})
    ('cref_flatfield_137.fits', 'cref_flatfield_137.fits')
    """
    def __init__(self, keyname, selections):
        if not isinstance(keyname, str):
            raise TypeError("First parameter should be variable name.")
        Selector.__init__(self, [keyname], selections)

    def choose(self, header):
        keyval = header[self._parameters[0]]
        index = 0
        while index < len(self._selections) and \
                keyval > self._selections[index][0]:
            index += 1
        if index == len(self._selections):
            choice1 = choice2 = self.get_choice(
                    self._selections[index-1], header)
        elif index == 0 or keyval == self._selections[index][0]:
            choice1 = choice2 = self.get_choice(
                    self._selections[index], header)
        else:
            choice1 = self.get_choice(self._selections[index-1], header)
            choice2 = self.get_choice(self._selections[index], header)
        return choice1, choice2

# ==============================================================================

RELATION_RE = re.compile('^([<=][=]?|default)(.*)$')

class VersionRelation(object):
    """A version relation consists of a relation operator <,=,== and an 
    expression representing a version.   VersionRelations can be compared to 
    themselves to support generating a sorted list:

    >>> s = VersionRelation('< 5')
    >>> t = VersionRelation('< 6')
    >>> s < t
    True
    >>> s == t
    False
    >>> s > t
    False
    >>> VersionRelation("= 4.5") < VersionRelation("= 5.0")
    True

    VersionRelations can be compared to versions to support choosing from a 
    sorted list:

    >>> 5 < s
    False
    >>> 5 == s
    False
    >>> 5 > s
    True
    >>> 5.0 < t
    True
    >>> 5.0 == t
    False
    >>> 6.1 > t
    True

    The special version 'default' is greater than all versions:

    >>> d = VersionRelation("default")
    >>> 5 < d
    True
    >>> 5 > d
    False
    >>> d > 51
    True
    >>> 5 == d
    False

    Versions don't have to be simple numbers:

    >>> e = VersionRelation("< (5,0,1)")
    >>> (5,0,0) < e
    True

    Non-numerical versions should only be compared to equivalent types:

    >>> (5,0) < VersionRelation('< 5.1')
    Traceback (most recent call last):
    ...
    ValueError: Incompatible version expression types: 5.1 and (5, 0)

    >>> VersionRelation('< 3.1') < 6
    True

    """
    def __init__(self, relation_str):
        match = RELATION_RE.match(relation_str)
        if not match:
            raise ValueError("RelationRelation " + repr(relation_str) + 
                             " does not begin with one of >,<,>=,<=,=,==")
        relation = match.group(1)
        if relation == "==":
            relation = "="
        self.relation = relation
        version = match.group(2).strip()
        if self.relation != "default":
            try:
                self.version = eval(version)
            except ValueError:
                raise ValueError("Invalid version expression.  Expression must"
                                 " evaluate to a comparable object.")
        else:
            if version:
                raise ValueError("Illegal version expression " + repr(version))
            self.version = "default"
            self.relation = "default"
            
    def __repr__(self):
        if self.version == "default":
            return "VersionRelation('default')"
        else:
            return 'VersionRelation(%s)' % \
                (repr(self.relation + " " + repr(self.version)))

    def compatible_types(self, other):
        """`other` is "compatible" if it is the same type as self.version,  or
        if both self.version and other are numerical.  Otherwise incompatible.
        """
        if type(self.version) == type(other):
            return True
        elif isinstance(other, (int, float, long)) and \
            isinstance(self.version, (int, float, long)):
            return True
        else:
            return False

    def __cmp__(self, other):
        if self.version == "default":
            result = 1
        elif isinstance(other, VersionRelation):
            if self.relation != other.relation and \
               self.version == other.version: # '<' < '=',  '<' < '=='
                result = cmp(self.relation, other.relation)  
            else:
                result = cmp(self.version, other.version)
        else:
            if self.compatible_types(other):
                result = cmp(self, VersionRelation("= " + str(other)))
            else:
                raise ValueError("Incompatible version expression types: " + 
                                 repr(self.version) + " and " + repr(other))
        return result

class VersionDepSelector(Selector):
    """VersionDep chooses from among it's selections based on a number of
    version relations. Each selection of a VersionDep consists of a version
    relation and a filename or nested Selector:

    ('< 5', 'cref_flatfield_518.fits')

    A special relation,  'default', is selected when none of the other relations
    applies:

    ('default', 'cref_flatfield_500.fits')

    Version relations are expressed as strings which consist of a relation
    symbol followed by an expression,  as in:

    '< 5.03'
    '= 6.66'
    '== 6.66'

    Version relations consist of two parts,  the relation symbol (=,==,<) and
    the version expression.  The simplest version expression consists of a 
    string which represents a number.   However,  the requirement on the 
    version expression (the remainder of the string following the relation) is 
    simply that it be eval()'able and that the result of the eval() supports 
    comparison operators.  Hence,  a more elaborate version selector might 
    look like:

    ('= (5,0,1)', 'cref_flatfield_501.fits')

    In this case the tuple (5,0,1) directly represents the common 
    representation of versions as major, minor, and point releases.   Note that
    for non-numerical version expressions,  the type of the eval'ed expression
    must exactly match the type of the choose()-time parameter,  i.e. in the 
    previous example the choose()-time parameter must be a tuple.
    """
    versionvar = "header variable name for this version kind"

    def __init__(self, selections):
        Selector.__init__(self, [], self.parse_selections(selections))

    def parse_selections(self, selections):
        """Convert relation string keys into runtime comparator objects."""
        return dict([(VersionRelation(x[0]), x[1]) for x in selections.items()])

    def choose(self, header):
        version = header[self.versionvar]
        index = 0
        while self._selections[index][0] < version:
            index += 1
        return self.get_choice(self._selections[index], header)

class SWVersionDepSelector(VersionDepSelector):
    """SWVersionDep represents using the client application s/w version as the
    selection criteria.  SWVersionDep implicitly uses the choose() method
    keyword parameter 'sw_version'.

    >>> r = SWVersionDepSelector({
    ...  '<3.1':    'cref_flatfield_65.fits',
    ...  '<5':      'cref_flatfield_73.fits',
    ...  'default': 'cref_flatfield_123.fits',
    ... })

    >>> r.choose({"sw_version":4.5})
    'cref_flatfield_73.fits'

    >>> r.choose({"sw_version":5})
    'cref_flatfield_123.fits'

    >>> r.choose({"sw_version":6})
    'cref_flatfield_123.fits'

    >>> r.choose({"sw_version":2.0})
    'cref_flatfield_65.fits'
    """
    versionvar = "sw_version"

# ==============================================================================

class ClosestTimeSelector(Selector):
    """ClosestTime chooses the selection whose time most closely matches the
    choose() method "time" keyword parameter

    >>> t = ClosestTimeSelector("time", {
    ...  '2017-4-24': "cref_flatfield_123.fits",
    ...  '2018-2-1':  "cref_flatfield_222.fits",
    ...  '2019-4-15': "cref_flatfield_123.fits",
    ... })

    >>> t.choose({"time":"2016-5-5"})
    'cref_flatfield_123.fits'

    >>> t.choose({"time":"2016-4-24"})
    'cref_flatfield_123.fits'

    >>> t.choose({"time":"2018-2-2"})
    'cref_flatfield_222.fits'

    >>> t.choose({"time":"2019-3-1"})
    'cref_flatfield_123.fits'

    >>> t.choose({"time":"2019-4-15"})
    'cref_flatfield_123.fits'

    >>> t.choose({"time":"2019-4-16"})
    'cref_flatfield_123.fits'
    """
    def __init__(self, timevar, selections):
        Selector.__init__(self, [timevar], selections)

    def choose(self, header):
        import numpy as np
        time = header[self._parameters[0]]
        diff = np.array([abs_time_delta(time, key) for key in self.keys()], 'f')
        index = np.argmin(diff)
        return self.get_choice(self._selections[index], header)

def str_to_datetime(string):
    """Convert a date string into a datetime object."""
    return datetime.datetime(*[int(x) for x in string.split("-")])

def abs_time_delta(time1, time2):
    """Return abs(time1 - time2) in total seconds."""
    date1 = str_to_datetime(time1)
    date2 = str_to_datetime(time2)
    return abs((date1-date2).total_seconds())


# ==============================================================================

class Parameters(object):
    """Parameters are a place to stash Selector parameters while an entire rmap
    is being read so that the header can be used to help instantiate the 
    selectors.
    
    When the rmap is compiled,  the selectors are compiled into Parameter 
    objects.  Later,  when both the full header and stubbed selectors are 
    available,  the Parameter objects are converted into Selectors by 
    instantiate().
    """
    selector = Selector   # Parameters is abstract class
    def __init__(self, selections):
        self.selections = selections
        
    def instantiate(self, parkeys, rmap_header):
        """Recursively construct Selector tree with `rmap_header` available."""
        mykeys = parkeys[0]
        otherkeys = parkeys[1:]
        selections = {}
        for key, selpars in self.selections.items():
            if isinstance(selpars, Parameters):
                selections[key] = selpars.instantiate(otherkeys, rmap_header)
            else:
                selections[key] = selpars
        return self.selector(mykeys, selections, rmap_header)

class MatchingParameters(Parameters):
    """Parameters for MatchingSelector"""
    selector = MatchingSelector
    
class UseAfterParameters(Parameters):
    """Parameters for UseAfterSelector"""
    selector = UseAfterSelector
    
    def instantiate(self, parkey, header):
        assert tuple(parkey[0]) == ("DATE-OBS","TIME-OBS")
        return Parameters.instantiate(self, parkey, header)

SELECTORS = {
    "Match"  : MatchingParameters,
    "UseAfter" : UseAfterParameters,
}

# ==============================================================================

def test():
    """Run module doctest."""
    import doctest, selectors
    return doctest.testmod(selectors)

if __name__ == "__main__":
    print test()
