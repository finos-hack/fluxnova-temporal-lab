/* global BpmnModeler, FluxnovaTemporalTask */
(function () {
  'use strict';

  var REST = '/engine-rest';
  var host = window.location.hostname;
  var COCKPIT = 'http://' + host + ':8080/fluxnova/app/cockpit/default/';
  var TASKLIST = 'http://' + host + ':8080/fluxnova/app/tasklist/default/';
  var CONTROL_CENTER = 'http://' + host + ':4000';
  var TEMPORAL_UI = 'http://' + host + ':8233';

  document.getElementById('link-cockpit').href = COCKPIT;
  document.getElementById('link-tasklist').href = TASKLIST;
  document.getElementById('link-control-center').href = CONTROL_CENTER;
  document.getElementById('link-temporal').href = TEMPORAL_UI;

  var EMPTY_DIAGRAM =
    '<?xml version="1.0" encoding="UTF-8"?>\n' +
    '<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" ' +
    'xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI" ' +
    'xmlns:dc="http://www.omg.org/spec/DD/20100524/DC" ' +
    'xmlns:camunda="http://camunda.org/schema/1.0/bpmn" ' +
    'id="Definitions_New" targetNamespace="http://fluxnova.finos.org/lab">\n' +
    '  <bpmn:process id="new-process" name="New process" isExecutable="true" camunda:historyTimeToLive="30">\n' +
    '    <bpmn:startEvent id="StartEvent_1" />\n' +
    '  </bpmn:process>\n' +
    '  <bpmndi:BPMNDiagram id="BPMNDiagram_1">\n' +
    '    <bpmndi:BPMNPlane id="BPMNPlane_1" bpmnElement="new-process">\n' +
    '      <bpmndi:BPMNShape id="StartEvent_1_di" bpmnElement="StartEvent_1">\n' +
    '        <dc:Bounds x="152" y="102" width="36" height="36" />\n' +
    '      </bpmndi:BPMNShape>\n' +
    '    </bpmndi:BPMNPlane>\n' +
    '  </bpmndi:BPMNDiagram>\n' +
    '</bpmn:definitions>\n';

  var modeler = new BpmnModeler({
    container: '#canvas',
    propertiesPanel: { parent: '#properties' },
    additionalModules: [ FluxnovaTemporalTask.TemporalTaskModule ],
    elementTemplates: [ FluxnovaTemporalTask.TEMPLATE ]
  });

  var statusEl = document.getElementById('status');
  var fileName = 'diagram.bpmn';

  function status(html, kind) {
    statusEl.innerHTML = html;
    statusEl.className = 'status' + (kind ? ' ' + kind : '');
  }

  function escapeHtml(text) {
    return String(text).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function open(xml, name) {
    fileName = name || fileName;
    return modeler.importXML(xml).then(function (result) {
      modeler.get('canvas').zoom('fit-viewport', 'auto');
      var warnings = (result.warnings || []).length;
      status('Opened <b>' + escapeHtml(fileName) + '</b>' +
        (warnings ? ' with ' + warnings + ' import warning(s)' : '') +
        '. Drag a <b>Temporal task</b> from the palette, or use the wrench menu on any task.');
    }).catch(function (err) {
      status('Could not open diagram: ' + escapeHtml(err.message), 'error');
    });
  }

  function processInfo() {
    var root = modeler.get('canvas').getRootElement().businessObject;
    var process = root.$type === 'bpmn:Process' ? root
      : (root.participants || []).map(function (p) { return p.processRef; }).filter(Boolean)[0];
    return process ? { key: process.id, name: process.name || process.id } : null;
  }

  function loadSample() {
    return fetch('diagrams/kyc-onboarding.bpmn')
      .then(function (r) { return r.text(); })
      .then(function (xml) { return open(xml, 'kyc-onboarding.bpmn'); });
  }

  function restError(response) {
    return response.text().then(function (text) {
      var message = text;
      try { message = JSON.parse(text).message || text; } catch (e) { /* plain text */ }
      throw new Error(response.status + ' ' + message);
    });
  }

  function deploy() {
    var info = processInfo();
    return modeler.saveXML({ format: true }).then(function (out) {
      var form = new FormData();
      form.append('deployment-name', info ? info.name : 'designer');
      form.append('deployment-source', 'fluxnova-temporal-designer');
      form.append('deploy-changed-only', 'true');
      form.append('data', new Blob([ out.xml ], { type: 'text/xml' }), fileName);
      status('Deploying…');
      return fetch(REST + '/deployment/create', { method: 'POST', body: form });
    }).then(function (response) {
      if (!response.ok) { return restError(response); }
      return response.json();
    }).then(function (deployment) {
      var defs = Object.keys(deployment.deployedProcessDefinitions || {}).length;
      status('Deployed <b>' + escapeHtml(deployment.name) + '</b> (' +
        (defs ? defs + ' new process version' : 'no changes') + '). ' +
        'Next: <b>Start instance</b>.', 'ok');
    }).catch(function (err) {
      status('Deployment failed: ' + escapeHtml(err.message), 'error');
    });
  }

  var dialog = document.getElementById('start-dialog');
  var startForm = document.getElementById('start-form');

  function openStartDialog() {
    var info = processInfo();
    if (!info) { status('No executable process in this diagram.', 'error'); return; }
    document.getElementById('start-process-key').textContent = info.key;
    startForm.businessKey.value = 'CUST-' + Math.floor(1000 + Math.random() * 9000);
    if (!startForm.variables.value) {
      startForm.variables.value = JSON.stringify({
        customerName: 'Ada Lovelace', country: 'FR', requestedAmount: 250000
      }, null, 2);
    }
    dialog.showModal();
  }

  function toTyped(values) {
    var typed = {};
    Object.keys(values).forEach(function (name) {
      var v = values[name];
      var type = typeof v === 'boolean' ? 'Boolean'
        : typeof v === 'number' ? (Number.isInteger(v) ? 'Long' : 'Double')
          : v === null ? 'Null'
            : typeof v === 'object' ? 'Json' : 'String';
      typed[name] = { value: type === 'Json' ? JSON.stringify(v) : v, type: type };
    });
    return typed;
  }

  dialog.addEventListener('close', function () {
    if (dialog.returnValue !== 'start') { return; }
    var info = processInfo();
    var variables;
    try {
      variables = JSON.parse(startForm.variables.value || '{}');
    } catch (e) {
      status('Variables are not valid JSON: ' + escapeHtml(e.message), 'error');
      return;
    }
    fetch(REST + '/process-definition/key/' + encodeURIComponent(info.key) + '/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ businessKey: startForm.businessKey.value, variables: toTyped(variables) })
    }).then(function (response) {
      if (!response.ok) { return restError(response); }
      return response.json();
    }).then(function (instance) {
      var link = COCKPIT + '#/process-instance/' + instance.id;
      status('Started <b>' + escapeHtml(instance.businessKey) + '</b>. ' +
        'Complete "Analyst review" in <a target="_blank" href="' + TASKLIST + '">Tasklist</a> (demo/demo), ' +
        'then follow it in <a target="_blank" href="' + link + '">Cockpit</a> and ' +
        '<a target="_blank" href="' + TEMPORAL_UI + '">Temporal UI</a>.', 'ok');
    }).catch(function (err) {
      status('Start failed: ' + escapeHtml(err.message) + ' (deploy the diagram first?)', 'error');
    });
  });

  function download() {
    modeler.saveXML({ format: true }).then(function (out) {
      var a = document.createElement('a');
      a.href = URL.createObjectURL(new Blob([ out.xml ], { type: 'application/xml' }));
      a.download = fileName;
      a.click();
      URL.revokeObjectURL(a.href);
    });
  }

  document.getElementById('btn-new').onclick = function () { open(EMPTY_DIAGRAM, 'new-process.bpmn'); };
  document.getElementById('btn-sample').onclick = loadSample;
  document.getElementById('btn-download').onclick = download;
  document.getElementById('btn-deploy').onclick = deploy;
  document.getElementById('btn-start').onclick = openStartDialog;
  document.getElementById('file-open').onchange = function (event) {
    var file = event.target.files[0];
    if (!file) { return; }
    file.text().then(function (xml) { open(xml, file.name); });
    event.target.value = '';
  };

  window.fluxnovaDesigner = modeler; // handy in the browser console
  loadSample();
})();
