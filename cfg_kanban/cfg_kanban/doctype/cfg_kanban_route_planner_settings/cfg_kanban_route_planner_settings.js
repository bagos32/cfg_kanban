frappe.ui.form.on('CFG Kanban Route Planner Settings', {
  setup(frm) {
    for (const field of ['source_warehouse', 'vehicle_warehouse']) {
      frm.set_query(field, () => ({ filters: { company: frm.doc.company || '', is_group: 0, disabled: 0,
        ...(field === 'vehicle_warehouse' ? { cfg_is_vehicle_warehouse: 1 } : {}) } }));
    }
  },
});
