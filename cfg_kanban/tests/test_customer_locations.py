"""Real pin parsing, normal Site validation and authorized route projection, offline."""
import copy,json,unittest
from unittest.mock import Mock
from cfg_kanban.services.customer_locations import delivery_pin,pin_geojson,pin_projection
from cfg_kanban.tests import test_driver_routes as routes
from cfg_kanban.tests import test_driver_route_actions as actions
from cfg_kanban.tests.test_vehicle_overview import Row,load

def geo(latitude=3.139,longitude=101.6869):
    return pin_geojson(dict(latitude=latitude,longitude=longitude))

class TestCustomerLocations(unittest.TestCase):
    def test_marker_uses_geojson_longitude_latitude_and_canonical_properties(self):
        raw=json.loads(geo());raw['features'][0]['properties']={'private_token':'secret','url':'javascript:alert(1)'}
        pin=delivery_pin(raw);self.assertEqual(pin,dict(latitude=3.139,longitude=101.6869))
        canonical=json.loads(pin_geojson(pin));self.assertEqual(canonical['features'][0]['geometry']['coordinates'],[101.6869,3.139]);self.assertEqual(canonical['features'][0]['properties'],{})
    def test_none_blank_null_or_deleted_feature_collection_means_no_pin(self):
        for value in (None,'','  ','null',{'type':'FeatureCollection','features':[]}):self.assertIsNone(delivery_pin(value))
    def test_zero_coordinates_and_boundary_values_are_real_pins(self):
        for lat,lng in ((0,0),(-90,-180),(90,180)):
            self.assertEqual(delivery_pin(geo(lat,lng)),dict(latitude=lat,longitude=lng))
    def test_feature_and_feature_collection_both_supported(self):
        feature=json.loads(geo())['features'][0];self.assertEqual(delivery_pin(feature),delivery_pin(geo()))
    def test_nonfinite_boolean_string_or_out_of_range_coordinates_rejected(self):
        for lat,lng in ((float('nan'),1),(1,float('inf')),(True,1),(1,False),('3',101),(91,1),(1,-181),(10**500,1)):
            raw=json.loads(geo());raw['features'][0]['geometry']['coordinates']=[lng,lat]
            with self.subTest(lat=lat,lng=lng),self.assertRaises(ValueError):delivery_pin(raw)
    def test_shapes_and_multiple_or_missing_markers_rejected(self):
        point=json.loads(geo())['features'][0]
        for raw in ({'type':'FeatureCollection','features':[point,point]}, {'type':'Feature','geometry':{'type':'LineString','coordinates':[[0,0],[1,1]]}}, {'type':'Point','coordinates':[0,0]}, {'type':'FeatureCollection'}, {'type':'Feature','geometry':{'type':'Point','coordinates':[1,2,3]}}):
            with self.subTest(raw=raw),self.assertRaises(ValueError):delivery_pin(raw)
    def test_circles_and_invalid_properties_are_not_delivery_entrance_pins(self):
        for props in ({'point_type':'circle','radius':100},{'point_type':'circlemarker'},'bad',[],True):
            raw=json.loads(geo());raw['features'][0]['properties']=props
            with self.subTest(props=props),self.assertRaises(ValueError):delivery_pin(raw)
    def test_bad_json_and_large_imports_reject_without_coercing_to_zero(self):
        for raw in ('bad-json','0','false','[]','x'*65537):
            with self.subTest(raw=raw[:20]),self.assertRaises(ValueError):delivery_pin(raw)
    def test_optional_route_projection_is_finite_only_and_invalid_does_not_throw(self):
        self.assertEqual(pin_projection(geo()),dict(delivery_pin=dict(latitude=3.139,longitude=101.6869),delivery_pin_status='Saved'))
        self.assertEqual(pin_projection('invalid'),dict(delivery_pin=None,delivery_pin_status='Invalid'))
        self.assertEqual(pin_projection(None)['delivery_pin_status'],'Missing')
    def site(self,raw):
        class Doc(Row):
            def is_new(self):return True
        f=Row(throw=lambda text:(_ for _ in ()).throw(ValueError(text)),db=Row(exists=lambda *a:True))
        ns=load('cfg_kanban/doctype/cfg_kanban_customer_scan_point/cfg_kanban_customer_scan_point.py',dict(frappe=f,Document=Doc,validate_price_list_mode=Mock(),validate_warehouse_company=Mock()))
        doc=ns['CFGKanbanCustomerScanPoint'](delivery_location=raw,require_gps=1,proof_policy='Required')
        return doc,ns
    def test_normal_site_validate_canonicalizes_pin_and_preserves_proof_policy(self):
        doc,_=self.site(json.loads(geo()));doc.validate();self.assertEqual(doc.delivery_location,geo());self.assertEqual(doc.require_gps,1);self.assertEqual(doc.proof_policy,'Required')
    def test_normal_site_validate_rejects_bad_pin_before_save(self):
        doc,_=self.site('bad');
        with self.assertRaisesRegex(ValueError,'valid map data'):doc.validate()
    def test_normal_site_validate_clears_a_deleted_pin(self):
        doc,_=self.site({'type':'FeatureCollection','features':[]});doc.validate();self.assertIsNone(doc.delivery_location)

class TestDriverLocationProjection(unittest.TestCase):
    def setUp(self):
        self.b=routes.TestDriverRoutes();self.b.setUp();self.addCleanup(self.b.doCleanups)
        self.site=self.b.data['CFG Kanban Customer Scan Point']['SITE1']
    def test_trip_projection_reads_current_site_pin_without_writing_trip(self):
        self.site.delivery_location=geo();before=copy.deepcopy(self.b.trip.as_dict());view=self.b.read()
        self.assertEqual(view['stops'][0]['delivery_pin'],dict(latitude=3.139,longitude=101.6869));self.assertEqual(view['stops'][0]['delivery_pin_status'],'Saved');self.assertEqual(self.b.trip.as_dict(),before)
    def test_legacy_missing_or_invalid_pin_keeps_existing_route_and_quantities(self):
        for raw,status in ((None,'Missing'),('bad','Invalid')):
            self.site.delivery_location=raw;stop=self.b.read()['stops'][0];self.assertEqual(stop['delivery_pin_status'],status);self.assertIsNone(stop['delivery_pin']);self.assertEqual(stop['items'][0]['loaded_qty'],4)
    def test_site_company_and_native_read_permissions_precede_pin_projection(self):
        self.site.delivery_location=geo();self.site.selling_company='B'
        with self.assertRaisesRegex(ValueError,'Company'):self.b.read()
        self.site.selling_company='A';self.site._denied=True
        with self.assertRaises(PermissionError):self.b.read()
    def test_pin_does_not_leak_from_unassigned_trip_or_other_company(self):
        self.site.delivery_location=geo();self.b.operator.employee='OTHER'
        with self.assertRaises(PermissionError):self.b.read()
        self.b.operator.employee='EMP';self.b.data['Company']['A']._denied=True
        with self.assertRaises(PermissionError):self.b.read()
    def test_visit_without_site_has_no_invented_customer_pin(self):
        source=copy.deepcopy(self.b.trip.stops[0]);source.customer_scan_point=None;source.stop_purpose='Visit Only'
        stop=self.b.ns['_stop'](self.b.trip,source,{})
        self.assertIsNone(stop['delivery_pin']);self.assertEqual(stop['address'],source.address_display)
    def test_office_pin_correction_does_not_invalidate_departure_snapshot(self):
        a=actions.TestDriverRouteActions();a.setUp();self.addCleanup(a.doCleanups);a.start();saved=json.loads(a.trip.driver_route_snapshot_json)
        a.data['CFG Kanban Customer Scan Point']['SITE1'].delivery_location=geo(4.1,102.2)
        view=a.v.read();self.assertEqual(view['stops'][0]['delivery_pin']['latitude'],4.1)
        self.assertEqual(actions.canonical('snapshot',a.ns['_execution'](a.trip,a.operator,view)),actions.canonical('snapshot',saved))
        self.assertEqual(a.context()['next_step'],'Begin Delivery');self.assertEqual(a.calls,[])

if __name__=='__main__':unittest.main()
