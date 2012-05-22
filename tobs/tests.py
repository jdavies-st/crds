"""Higher level mapping based tests for selectors not covered by hst.
"""

from crds import rmap

import unittest

class TestSelectors(unittest.TestCase):

    def setUp(self):
        self.rmap = rmap.get_cached_mapping("tobs_tinstr_tfilekind.rmap")
    
    def _selector_testcase(self, case, parameter, result):
        header = {
            "TEST_CASE": case,
            "PARAMETER": parameter,
        }
        bestref = self.rmap.get_best_ref(header)
        self.assertEqual(bestref, result)
        
    def test_use_after_bad_datetime(self):
        with self.assertRaises(rmap.ValidationError):
            self._selector_testcase('USE_AFTER', '4.5', 'cref_flatfield_73.fits')

    def test_use_after_no_time(self):
        self._selector_testcase('USE_AFTER', '2005-12-20', 'o9f15549j_bia.fits')

    def test_use_after_nominal(self):
        self._selector_testcase('USE_AFTER', '2005-12-20', 'o9f15549j_bia.fits')

    def test_use_after_missing_parameter(self):
        header = { "TEST_CASE": "USE_AFTER" }  # no PARAMETER
        with self.assertRaisesRegexp(
            rmap.ValidationError, 
            "UseAfter required lookup parameter 'PARAMETER' is undefined."):
            bestref = self.rmap.get_best_ref(header)

    def test_select_version1(self): 
        self._selector_testcase('SELECT_VERSION', '4.5', 'cref_flatfield_73.fits')
    def test_select_version2(self): 
        self._selector_testcase('SELECT_VERSION', '5', 'cref_flatfield_123.fits')
    def test_select_version3(self): 
        self._selector_testcase('SELECT_VERSION', '6', 'cref_flatfield_123.fits')
    def test_select_version4(self): 
        self._selector_testcase('SELECT_VERSION', '2.0', 'cref_flatfield_65.fits')
        
    def test_closest_time1(self):
        self._selector_testcase('CLOSEST_TIME', '2016-05-05', 'cref_flatfield_123.fits')
    def test_closest_time2(self):
        self._selector_testcase('CLOSEST_TIME', '2016-04-24', 'cref_flatfield_123.fits')
    def test_closest_time3(self):
        self._selector_testcase('CLOSEST_TIME', '2018-02-02', 'cref_flatfield_222.fits')
    def test_closest_time4(self):
        self._selector_testcase('CLOSEST_TIME', '2019-03-01', 'cref_flatfield_123.fits')
    def test_closest_time5(self):
        self._selector_testcase('CLOSEST_TIME', '2016-04-15', 'cref_flatfield_123.fits')
    def test_closest_time6(self):
        self._selector_testcase('CLOSEST_TIME', '2016-04-16', 'cref_flatfield_123.fits')

    def test_bracket1(self):
        self._selector_testcase('BRACKET', '1.25',     
            ('cref_flatfield_120.fits', 'cref_flatfield_124.fits'))
    def test_bracket2(self):
        self._selector_testcase('BRACKET', '1.2',     
            ('cref_flatfield_120.fits', 'cref_flatfield_120.fits'))
    def test_bracket3(self):
        self._selector_testcase('BRACKET', '1.5',     
            ('cref_flatfield_124.fits', 'cref_flatfield_124.fits'))
    def test_bracket4(self):
        self._selector_testcase('BRACKET', '5.0',     
            ('cref_flatfield_137.fits', 'cref_flatfield_137.fits'))
    def test_bracket5(self):
        self._selector_testcase('BRACKET', '1.0',
            ('cref_flatfield_120.fits', 'cref_flatfield_120.fits'))
    def test_bracket6(self):
        self._selector_testcase('BRACKET', '6.0',
            ('cref_flatfield_137.fits', 'cref_flatfield_137.fits'))

    def test_geometrically_nearest1(self):
        self._selector_testcase("GEOMETRICALLY_NEAREST", '1.0', 'cref_flatfield_120.fits')
    def test_geometrically_nearest2(self):
        self._selector_testcase("GEOMETRICALLY_NEAREST", '1.2', 'cref_flatfield_120.fits')
    def test_geometrically_nearest3(self):
        self._selector_testcase("GEOMETRICALLY_NEAREST", '1.25', 'cref_flatfield_120.fits')
    def test_geometrically_nearest4(self):
        self._selector_testcase("GEOMETRICALLY_NEAREST", '1.4', 'cref_flatfield_124.fits')
    def test_geometrically_nearest5(self):
        self._selector_testcase("GEOMETRICALLY_NEAREST", '3.25', 'cref_flatfield_124.fits')
    def test_geometrically_nearest6(self):
        self._selector_testcase("GEOMETRICALLY_NEAREST", '3.26', 'cref_flatfield_137.fits')
    def test_geometrically_nearest7(self):
        self._selector_testcase("GEOMETRICALLY_NEAREST", '5.0', 'cref_flatfield_137.fits')
    def test_geometrically_nearest8(self):
        self._selector_testcase("GEOMETRICALLY_NEAREST", '5.1', 'cref_flatfield_137.fits')

if __name__ == '__main__':
    unittest.main()

