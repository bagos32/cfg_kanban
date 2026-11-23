frappe.pages['kanban-return-qc'].on_page_load = function(wrapper) {
  const ready=frappe.require([
    '/assets/cfg_kanban/css/return_qc_monitor.css',
    '/assets/cfg_kanban/js/return_qc_monitor.js',
  ]).then(()=>window.cfg_return_qc.mount(wrapper));
  const show=async()=>{const view=await ready;if(frappe.get_route()?.[0]!=='kanban-return-qc')return;
    await view.show(frappe.get_route()[1]||null);
  };
  frappe.pages['kanban-return-qc'].on_page_show=show;
  frappe.pages['kanban-return-qc'].on_page_hide=()=>ready.then(view=>view.hide());
  show();
};
