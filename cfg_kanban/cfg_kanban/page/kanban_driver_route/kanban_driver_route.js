frappe.pages['kanban-driver-route'].on_page_load = function (wrapper) {
  const ready = frappe.require([
    '/assets/cfg_kanban/js/map_defaults.js',
    '/assets/cfg_kanban/css/delivery_maps.css',
    '/assets/cfg_kanban/js/trip_gps.js',
    '/assets/cfg_kanban/js/delivery_maps.js',
    '/assets/cfg_kanban/js/driver_route.js',
    '/assets/cfg_kanban/js/driver_route_actions.js',
    '/assets/cfg_kanban/js/vendor/html2canvas-1.4.1.min.js',
    '/assets/cfg_kanban/js/mobile_print_bridge.js',
    '/assets/cfg_kanban/js/driver_mobile_print.js',
    '/assets/cfg_kanban/js/delivery_action_scanner.js',
    '/assets/cfg_kanban/js/dispatch_recovery.js',
    '/assets/cfg_kanban/js/delivery_proof_tools.js',
  ]).then(() => {
    wrapper.cfg_driver_route = window.cfg_driver_route.mount(wrapper);
    return wrapper.cfg_driver_route;
  });
  const show = async () => {
    const view = await ready;
    if (frappe.get_route()?.[0] === 'kanban-driver-route') await view.show(frappe.get_route()[1] || null);
  };
  frappe.pages['kanban-driver-route'].on_page_show = show;
  frappe.pages['kanban-driver-route'].on_page_hide = () => ready.then(view => view.hide());
  show();
};
