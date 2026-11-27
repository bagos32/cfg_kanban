frappe.pages['kanban-trip-handover'].on_page_load=function(wrapper){
 const ready=frappe.require(['/assets/cfg_kanban/js/field_ui.js','/assets/cfg_kanban/css/trip_handover.css','/assets/cfg_kanban/js/dispatch_recovery.js','/assets/cfg_kanban/js/dispatch_review.js','/assets/cfg_kanban/js/trip_handover.js']).then(()=>window.cfg_trip_handover.mount(wrapper));
 const show=async()=>{const view=await ready;if(frappe.get_route()?.[0]==='kanban-trip-handover')await view.show(frappe.get_route()[1]||null);};
 frappe.pages['kanban-trip-handover'].on_page_show=show;
 frappe.pages['kanban-trip-handover'].on_page_hide=()=>ready.then(view=>view.hide());
 show();
};
