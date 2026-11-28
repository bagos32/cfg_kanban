/* Normal Desk form component; mock fixtures only, never a driver/floor posting action. */
(function (root, factory) {
  const api = factory(root);
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.cfg_route_planner = api;
})(typeof window !== 'undefined' ? window : globalThis, function (root) {
  const tr = text => root.__ ? root.__(text) : text;
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const prefix = 'cfg_kanban.services.route_planner.';
  const rpc = async (method, args) => (await root.frappe.call({ method: prefix + method, args })).message;
  const roles = ['Stock Manager', 'Sales Manager', 'System Manager', 'CFG Kanban System Maintenance'];
  const canWrite = frm => Boolean(frm.perm?.some(row => row.write)) && (root.frappe.user_roles || []).some(role => roles.includes(role));
  const clean = frm => !frm.is_new() && !frm.is_dirty();
  function displayTime(value) {
    if (!value) return '—';
    return String(value).replace('T', ' ').replace('+08:00', ' MYT');
  }
  function render(data, selected, reason, busy, error) {
    const run = (data.runs || []).find(row => row.name === selected);
    const action = (name, label, enabled = true) => `<button type="button" class="btn btn-default btn-sm mr-2 mb-2" data-planner-action="${name}"${busy || !enabled ? ' disabled' : ''}>${tr(label)}</button>`;
    return `<div class="alert alert-warning"><strong>${tr('Mock Route Planner — test fixtures only')}</strong><br>${tr('No Google request, road routing, traffic estimate, savings calculation or stock posting. Acceptance changes only this Draft stop order and its normal LIFO instructions.')}</div>
      ${error ? `<div role="alert" class="alert alert-danger">${escape(error)}</div>` : ''}
      <div>${action('refresh', 'Refresh Readiness / History')}${action('settings', 'Company Planner Settings')}${action('request', 'Generate Mock Proposal', data.ready)}</div>
      <p><strong>${tr('Data readiness')}: ${tr(data.ready ? 'Ready for a mock request' : 'Needs attention')}</strong> · ${tr('Packed load')}: ${escape(data.total_load_grams || 0)} g</p>
      <ul>${(data.errors || []).map(value => `<li class="text-danger">${escape(value)}</li>`).join('')}${(data.warnings || []).map(value => `<li>${escape(value)}</li>`).join('')}</ul>
      <label>${tr('Proposal history')}</label><select class="form-control mb-3" data-planner-run${busy ? ' disabled' : ''}>
      ${(data.runs || []).map(row => `<option value="${escape(row.name)}"${row.name === selected ? ' selected' : ''}>${escape(row.name)} · ${escape(row.status)}${row.stale && row.status !== 'Accepted' ? ' · ' + tr('Stale inputs') : ''}</option>`).join('') || `<option value="">${tr('No requests yet')}</option>`}</select>
      ${run ? `<p><strong>${escape(run.name)} · ${escape(run.status)}</strong> · ${tr('Source revision')}: ${escape(run.source_revision)} · ${tr('Attempt')}: ${escape(run.attempt_count)}</p>
        ${run.stale && run.status !== 'Accepted' ? `<div class="alert alert-warning">${tr('Inputs changed. Save the Trip and generate a fresh proposal; the old result cannot be accepted.')}</div>` : ''}
        ${run.failure ? `<p role="alert" class="text-danger">${escape(run.failure)}</p>` : ''}
        <div class="table-responsive"><table class="table table-bordered"><thead><tr><th>${tr('Original order')}</th><th>${tr('Mock proposed order')}</th><th>${tr('Simulated service start (MYT)')}</th></tr></thead><tbody>
        ${(run.original || []).map((row, index) => { const proposed = run.proposed?.[index]; return `<tr><td>${index + 1}. ${escape(row.site_name || row.customer)}<br><small>${escape(row.stop_key)}</small></td><td>${proposed ? `${index + 1}. ${escape(proposed.site_name || proposed.customer)}<br><small>${escape(proposed.stop_key)}</small>` : '—'}</td><td>${escape(displayTime(proposed?.start_time))}</td></tr>`; }).join('')}
        </tbody></table></div><p>${tr('Simulated depot return')}: ${escape(displayTime(run.end_time))}. ${tr('No equivalent road baseline is available; no savings are claimed.')}</p>
        ${run.accepted_by ? `<p>${tr('Accepted by')}: ${escape(run.accepted_by)} · ${escape(run.accepted_on)} · ${tr('Resulting revision')}: ${escape(run.resulting_revision)}</p>` : ''}
        ${run.decision_reason ? `<p>${tr('Decision reason')}: ${escape(run.decision_reason)}</p>` : ''}
        <label>${tr('Decision / retry reason')}</label><textarea class="form-control mb-3" maxlength="500" data-planner-reason${busy ? ' disabled' : ''}>${escape(reason)}</textarea>
        ${action('accept', 'Accept Mock Proposal', run.status === 'Ready' && !run.stale && data.ready)}
        ${action('reject', 'Reject Proposal', ['Ready', 'Failed', 'Timed Out'].includes(run.status))}
        ${action('retry', 'Retry Original Mock', ['Failed', 'Timed Out'].includes(run.status) && !run.stale && data.ready)}
        ${action('interrupt', 'Mark Interrupted (after 90 seconds)', ['Queued', 'Running'].includes(run.status))}` : ''}
      <p class="text-muted">${tr('Mark Planned and existing dispatch actions still own preparation. If a reply is lost, refresh history before retrying the same Run. Earlier runs remain in the normal Route Planning Run list.')}</p>`;
  }
  function mount(frm) {
    const wrapper = frm.fields_dict.planner_panel.$wrapper;
    let epoch = 0, destroyed = false, busy = false, timer, data, selected = '', reason = '', error = '', polls = 0;
    const context = () => [frm.doc.name, frm.doc.company, String(frm.doc.modified || '')].join('|');
    const current = (token, identity) => !destroyed && token === epoch && context() === identity && clean(frm);
    const draw = () => { if (!destroyed && data) wrapper.html(render(data, selected, reason, busy, error)); };
    async function refresh() {
      root.clearTimeout(timer);
      if (destroyed) return;
      if (!canWrite(frm) || !clean(frm)) {
        epoch++; wrapper.html(`<p class="text-muted">${tr('Save this Trip and use an authorised office editor account to review mock planning.')}</p>`); return;
      }
      const identity = context(), token = ++epoch;
      try {
        const result = await rpc('get_planning_panel', { trip_name: frm.doc.name });
        if (!current(token, identity)) return;
        data = result;
        if (!(data.runs || []).some(row => row.name === selected)) selected = data.runs?.[0]?.name || '';
        draw();
        const selectedRun = (data.runs || []).find(row => row.name === selected);
        if (selectedRun && ['Queued', 'Running'].includes(selectedRun.status) && polls++ < 30) {
          timer = root.setTimeout(() => {
            if (!frm.wrapper?.is || frm.wrapper.is(':visible')) refresh();
          }, 3000);
        }
      } catch (_) {
        if (current(token, identity)) wrapper.html(`<div role="alert" class="alert alert-danger">${tr('Could not load planning readiness. Correct the server message, then refresh this form. Manual planning remains available.')}</div>`);
      }
    }
    async function act(action) {
      if (busy || destroyed) return;
      if (!clean(frm) || !canWrite(frm)) { await refresh(); return; }
      if (action === 'settings') {
        if (data?.settings) return root.frappe.set_route('Form', 'CFG Kanban Route Planner Settings', data.settings);
        return root.frappe.new_doc('CFG Kanban Route Planner Settings', { company: frm.doc.company });
      }
      if (action === 'refresh') { polls = 0; error = ''; return refresh(); }
      const run = data?.runs?.find(row => row.name === selected);
      if (action !== 'request' && (!run || !reason.trim())) { error = tr('Select the exact Run and enter a reason first.'); draw(); return; }
      const identity = context();
      busy = true; error = ''; root.clearTimeout(timer); draw();
      try {
        let result;
        if (action === 'request') result = await rpc('request_mock_proposal', { trip_name: frm.doc.name, expected_modified: frm.doc.modified });
        else if (action === 'retry') result = await rpc('retry_mock_proposal', { run_name: run.name, reason });
        else if (['accept', 'reject', 'interrupt'].includes(action)) result = await rpc('decide_mock_proposal', {
          run_name: run.name, decision: { accept: 'Accept', reject: 'Reject', interrupt: 'Mark Interrupted' }[action], reason });
        if (destroyed || identity !== context() || !clean(frm)) return;
        selected = result?.run?.name || result?.name || selected;
        if (result?.accepted) { await frm.reload_doc(); return; }
      } catch (_) {
        if (!destroyed && identity === context()) error = tr('Action not confirmed. Refresh history and read the server message before retrying this same Run.');
      } finally {
        busy = false;
        if (!destroyed && identity === context()) await refresh();
      }
    }
    wrapper.off('.cfg_planner').on('click.cfg_planner', '[data-planner-action]', event => {
      act(root.$(event.currentTarget).attr('data-planner-action'));
    }).on('change.cfg_planner', '[data-planner-run]', event => {
      selected = root.$(event.currentTarget).val(); error = ''; polls = 0; refresh();
    }).on('input.cfg_planner', '[data-planner-reason]', event => { reason = root.$(event.currentTarget).val(); });
    refresh();
    return { refresh, act, select(name) { selected = name; draw(); }, reason(value) { reason = value; },
      destroy() { destroyed = true; epoch++; root.clearTimeout(timer); wrapper.off('.cfg_planner'); } };
  }
  return { mount, render, canWrite };
});
