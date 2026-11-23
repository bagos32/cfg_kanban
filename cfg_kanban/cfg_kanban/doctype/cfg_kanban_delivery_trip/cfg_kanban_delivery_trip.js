frappe.ui.form.on('CFG Kanban Delivery Trip', {
  async setup(frm) {
    for (const [name,kind] of [['dispatch_profile','Customer Order'],['open_route_profile','Open Route Stock']]) frm.set_query(name,()=>({filters:{active:1,company:frm.doc.company||'',plan_type:kind,fulfilment_mode:'Vehicle Delivery'}}));
    frm.set_query('driver', () => ({ filters: { status: 'Active' } }));
    frm.set_query('employee','assistant_drivers',()=>({filters:{status:'Active'}}));
    frm.set_query('route_template', () => ({ filters: { active: 1, company: frm.doc.company || '' } }));
    for (const name of ['source_warehouse', 'vehicle_warehouse']) frm.set_query(name, () => ({ filters: {
      company: frm.doc.company || '', is_group: 0, disabled: 0, ...(name === 'vehicle_warehouse' ? { cfg_is_vehicle_warehouse: 1 } : {}) } }));
    frm.fields_dict.stops.grid.get_field('customer_scan_point').get_query = () => ({ filters: { active: 1, selling_company: frm.doc.company || '' } });
    frm.fields_dict.stops.grid.get_field('customer_address').get_query = (_doc, cdt, cdn) => ({ filters: [
      ['Dynamic Link', 'link_doctype', '=', 'Customer'], ['Dynamic Link', 'link_name', '=', locals[cdt][cdn].customer || ''] ] });
    frm.fields_dict.dispatch_plans.grid.get_field('dispatch_plan').get_query = () => ({ filters: {
      company: frm.doc.company || '', plan_type: 'Customer Order', fulfilment_mode: 'Vehicle Delivery' } });
    await frappe.require('/assets/cfg_kanban/js/office_delivery_trip.js');
  },
  async refresh(frm) {
    await frappe.require('/assets/cfg_kanban/js/office_delivery_trip.js');
    const ui = window.cfg_office_delivery_trip;
    frm.set_df_property?.('assistant_drivers','read_only',!ui.editable(frm)||['In Progress','Completed','Closed Incomplete'].includes(frm.doc.driver_route_state));
    frm.set_df_property?.('vehicle_warehouse','read_only',['In Progress','Completed','Closed Incomplete'].includes(frm.doc.driver_route_state));
    frm.set_df_property?.('driver','read_only',['In Progress','Completed','Closed Incomplete'].includes(frm.doc.driver_route_state));
    if (!frm.is_new() && (frappe.user_roles||[]).some(role=>['Stock Manager','Manufacturing Manager','System Manager'].includes(role))) frm.add_custom_button(__('Supervisor Live Map'), () => frappe.set_route('kanban-trip-monitor', frm.doc.name));
    if (!frm.is_new()) frm.add_custom_button(__('Driver Route'), () => frappe.set_route('kanban-driver-route', frm.doc.name));
    frm.fields_dict.planning_help.$wrapper.html(`<p class="text-muted">${__('Assign orders and extra route stock here. Enable Generate Dispatch on Mark Planned to create linked warehouse work automatically. One shared Open Route pool serves optional-sale visits. Load the last delivery stop first.')}</p>`);
    if (ui.editable(frm)) frm.add_custom_button(__('Load Route Template'), () => ui.loadTemplate(frm));
    frm.add_custom_button(__('Refresh SO Inbox'), () => ui.inbox(frm, 'order_inbox', true));
    if (!frm.is_new()) frm.add_custom_button(__('Refresh Loading Details'), () => ui.loading(frm));
    if (!frm.is_new() && frm.perm?.[0]?.write && !frm.doc.vehicle_warehouse && frm.doc.driver_route_snapshot_json && ['In Progress','Completed','Closed Incomplete'].includes(frm.doc.driver_route_state)) frm.add_custom_button(__('Sync Lorry Assignment'), async()=>{
      if(frm.is_dirty()){ui.alert(frm,__('Reload the Trip before syncing its departure lorry.'));return;}
      if(frm.__cfg_lorry_sync_busy)return;frm.__cfg_lorry_sync_busy=true;
      try {await frappe.call({method:'cfg_kanban.services.driver_route_actions.sync_trip_lorry',args:{trip_name:frm.doc.name,expected_modified:frm.doc.modified},freeze:true,freeze_message:__('Syncing the departure lorry...')});await frm.reload_doc();}
      finally {frm.__cfg_lorry_sync_busy=false;}
    });
    if (ui.editable(frm) && !frm.is_new() && !['In Progress','Completed'].includes(frm.doc.driver_route_state)) frm.add_custom_button(__('Generate / Refresh Dispatch'), async()=>{
      if(frm.is_dirty()){ui.alert(frm,__('Save the Trip and its quantities before generating dispatch work.'));return;}
      if(frm.__cfg_dispatch_busy)return;frm.__cfg_dispatch_busy=true;
      try {await frappe.call({method:'cfg_kanban.services.trip_dispatch.generate_dispatch_for_trip',args:{trip_name:frm.doc.name,expected_modified:frm.doc.modified},freeze:true,freeze_message:__('Generating linked dispatch work...')});await frm.reload_doc();}
      finally {frm.__cfg_dispatch_busy=false;}
    });
    if (ui.editable(frm) && !frm.is_new()) {
      for (const state of ['Draft', 'Planned', 'Closed', 'Cancelled']) {
        if (state === frm.doc.state) continue;
        frm.add_custom_button(__(state === 'Draft' ? 'Return to Draft' : state === 'Planned' ? 'Mark Planned' : state === 'Closed' ? 'Close Planning' : 'Cancel Planning'), async () => {
          if (['Closed', 'Cancelled'].includes(state) && !(frm.doc.closure_reason || '').trim()) {
            ui.alert(frm, __('Enter Closure / Cancellation Reason in Notes and History first.')); return;
          }
          const previous = frm.doc.state;
          try { await frm.set_value('state', state); await frm.save(); }
          catch (error) { await frm.set_value('state', previous); ui.alert(frm, __('Planning status was not saved. Correct the reported error and save again.')); }
        }, __('Planning Status'));
      }
    }
    ui.renumber(frm);
    if (frm.doc.route_template) await ui.inbox(frm, 'order_inbox', true);
  },
  async route_template(frm) {
    if (window.cfg_office_delivery_trip && frm.doc.route_template && !(frm.doc.stops || []).length) await window.cfg_office_delivery_trip.loadTemplate(frm);
  },
  async driver(frm) {
    const employee=frm.doc.driver;
    await frm.set_value('driver_display',employee||'');
    if(!employee||frm.doc.driver!==employee)return;
    const result=await frappe.db.get_value('Employee',employee,'employee_name');
    if(frm.doc.driver!==employee)return;
    const name=result.message?.employee_name;
    await frm.set_value('driver_display',name&&name!==employee?`${name} (${employee})`:employee);
  },
  validate(frm) { window.cfg_office_delivery_trip?.renumber(frm); },
});
frappe.ui.form.on('CFG Kanban Delivery Trip Stop', {
  stops_add(frm, cdt, cdn) { locals[cdt][cdn].stop_key = 'S' + frappe.utils.get_random(20); window.cfg_office_delivery_trip?.renumber(frm); },
  stops_move(frm) { window.cfg_office_delivery_trip?.renumber(frm); },
  stops_remove(frm) { window.cfg_office_delivery_trip?.renumber(frm); },
  customer_scan_point(frm, cdt, cdn) { return window.cfg_office_delivery_trip.site(frm, cdt, cdn); },
});
frappe.ui.form.on('CFG Kanban Delivery Trip Plan', {
  stop_sequence(frm, cdt, cdn) {
    const row = locals[cdt][cdn]; const stop = (frm.doc.stops || [])[Number(row.stop_sequence) - 1];
    frappe.model.set_value(cdt, cdn, 'stop_key', stop?.stop_key || '');
  },
});

frappe.ui.form.on('CFG Kanban Trip Stock', {
  async item_code(frm,cdt,cdn) {
    const row=locals[cdt][cdn],code=row.item_code;
    const result=await frappe.db.get_value('Item',code,'stock_uom');
    if(row.item_code===code)await frappe.model.set_value(cdt,cdn,'stock_uom',result.message?.stock_uom||'');
  },
});
