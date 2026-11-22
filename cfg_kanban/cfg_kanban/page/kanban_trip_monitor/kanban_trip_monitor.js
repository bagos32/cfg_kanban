frappe.pages['kanban-trip-monitor'].on_page_load = function(wrapper) {
  const ready=frappe.require([
    '/assets/cfg_kanban/js/map_defaults.js',
    '/assets/cfg_kanban/css/delivery_maps.css',
    '/assets/cfg_kanban/js/delivery_maps.js',
    '/assets/cfg_kanban/js/driver_route.js',
    '/assets/cfg_kanban/js/driver_route_actions.js',
    '/assets/cfg_kanban/js/trip_monitor.js',
  ]).then(()=>window.cfg_trip_monitor.mount(wrapper));
  const show=async()=>{const view=await ready;if(frappe.get_route()?.[0]!=='kanban-trip-monitor')return;
    const name=frappe.route_options?.cfg_trip_monitor_trip||frappe.get_route()[1]||null;
    if(frappe.route_options?.cfg_trip_monitor_trip)delete frappe.route_options.cfg_trip_monitor_trip;
    await view.show(name);
  };
  frappe.pages['kanban-trip-monitor'].on_page_show=show;
  frappe.pages['kanban-trip-monitor'].on_page_hide=()=>ready.then(view=>view.hide());
  show();
};
