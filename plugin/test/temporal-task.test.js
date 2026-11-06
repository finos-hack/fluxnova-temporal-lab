'use strict';

// Runs with plain Node (no bpmn-js install): bpmn-js services are stubbed.
const test = require('node:test');
const assert = require('node:assert/strict');

const plugin = require('../src/temporal-task.js');

// --- minimal moddle stand-in ---------------------------------------------
function makeModdle(prefix = 'camunda') {
  const known = new Set([
    'bpmn:ServiceTask', 'bpmn:ExtensionElements',
    `${prefix}:InputOutput`, `${prefix}:InputParameter`, `${prefix}:ExecutionListener`
  ]);
  function element(type, props) {
    const el = { $type: type, $attrs: {} };
    Object.assign(el, props);
    el.get = (name) => (name in el ? el[name] : undefined);
    el.set = (name, value) => { el[name] = value; };
    return el;
  }
  return {
    getType(name) {
      if (!known.has(name)) throw new Error(`unknown type <${name}>`);
      return function Type() {};
    },
    create(type, props = {}) {
      this.getType(type);
      return element(type, props);
    }
  };
}

function makeEventBus() {
  const handlers = {};
  return {
    on(events, priority, fn) {
      if (typeof priority === 'function') { fn = priority; }
      [].concat(events).forEach((e) => { (handlers[e] = handlers[e] || []).push(fn); });
    },
    fire(e, ctx) { return (handlers[e] || []).map((fn) => fn({ type: e }, ctx)); },
    handlers
  };
}

function makeElementTemplates(eventBus) {
  let templates = [];
  return {
    get: (id) => templates.find((t) => t.id === id) || null,
    getAll: () => templates.slice(),
    set(list) { templates = list; eventBus.fire('elementTemplates.changed'); }
  };
}

function makeInjector(services) {
  return { get: (name, strict) => (name in services ? services[name] : (strict === false ? null : (() => { throw new Error(name); })())) };
}

const translate = (s) => s;

// --- tests ---------------------------------------------------------------

test('template is a valid C7 element template for service tasks', () => {
  const t = plugin.TEMPLATE;
  assert.equal(t.id, 'org.finos.fluxnova.temporal.TemporalTask');
  assert.deepEqual(t.appliesTo, [ 'bpmn:ServiceTask' ]);
  assert.equal(t.version, undefined, 'unversioned so elementTemplates.get(id) finds it');
  const hidden = t.properties.filter((p) => p.type === 'Hidden').map((p) => [ p.binding.name, p.value ]);
  assert.deepEqual(hidden, [ [ 'camunda:type', 'external' ], [ 'camunda:topic', 'temporal' ] ]);
  const inputs = t.properties.filter((p) => p.binding.type === 'camunda:inputParameter').map((p) => p.binding.name);
  assert.deepEqual(inputs, plugin.DEFAULT_INPUTS.map((i) => i.name));
  const groups = new Set(t.groups.map((g) => g.id));
  t.properties.filter((p) => p.group).forEach((p) => assert.ok(groups.has(p.group), p.label));
});

test('palette creates a configured Temporal task and registers the template', () => {
  const eventBus = makeEventBus();
  const moddle = makeModdle();
  const elementTemplates = makeElementTemplates(eventBus);
  const injector = makeInjector({ elementTemplates });
  let provider;
  const palette = { registerProvider: (p) => { provider = p; } };
  let started;
  const create = { start: (event, shape) => { started = shape; } };
  const elementFactory = { createShape: (attrs) => ({ type: attrs.type, businessObject: attrs.businessObject, width: 100, height: 80 }) };

  new plugin.TemporalTaskModule.temporalTemplateRegistrar[1](eventBus, injector);
  assert.ok(elementTemplates.get(plugin.TEMPLATE_ID), 'registered at init');

  new plugin.TemporalTaskModule.temporalPaletteProvider[1](palette, create, elementFactory, moddle, injector, translate);
  const entry = provider.getPaletteEntries()['create.temporal-task'];
  assert.equal(entry.group, 'activity');
  assert.match(entry.imageUrl, /^data:image\/svg\+xml/);

  entry.action.click({});
  const bo = started.businessObject;
  assert.equal(started.type, 'bpmn:ServiceTask');
  assert.equal(bo['camunda:type'], 'external');
  assert.equal(bo['camunda:topic'], 'temporal');
  assert.equal(bo['camunda:modelerTemplate'], plugin.TEMPLATE_ID);
  const io = bo.extensionElements.values[0];
  assert.equal(io.$type, 'camunda:InputOutput');
  assert.equal(io.$parent, bo.extensionElements);
  assert.equal(bo.extensionElements.$parent, bo);
  assert.deepEqual(io.inputParameters.map((p) => p.name), plugin.DEFAULT_INPUTS.map((i) => i.name));
  assert.ok(plugin.isTemporalTask(started));
});

test('template is re-added after a loader replaces the template list', () => {
  const eventBus = makeEventBus();
  const elementTemplates = makeElementTemplates(eventBus);
  new plugin.TemporalTaskModule.temporalTemplateRegistrar[1](eventBus, makeInjector({ elementTemplates }));
  elementTemplates.set([ { id: 'other' } ]);
  assert.ok(elementTemplates.get('other'));
  assert.ok(elementTemplates.get(plugin.TEMPLATE_ID));
});

test('works with the fluxnova moddle prefix too', () => {
  const props = plugin.buildTemporalProperties(makeModdle('fluxnova'));
  assert.equal(props['fluxnova:topic'], 'temporal');
  assert.equal(props.extensionElements.values[0].$type, 'fluxnova:InputOutput');
});

test('replace menu converts a task and keeps unrelated extension elements', () => {
  const moddle = makeModdle();
  const eventBus = makeEventBus();
  const listener = moddle.create('camunda:ExecutionListener', {});
  const oldIo = moddle.create('camunda:InputOutput', {});
  const userTask = { businessObject: moddle.create('bpmn:ServiceTask', {}) };
  userTask.businessObject.$type = 'bpmn:UserTask';
  const replaced = { businessObject: moddle.create('bpmn:ServiceTask', {
    extensionElements: moddle.create('bpmn:ExtensionElements', { values: [ listener, oldIo ] })
  }) };

  let menu, updated;
  const popupMenu = { registerProvider: (id, p) => { assert.equal(id, 'bpmn-replace'); menu = p; } };
  const bpmnReplace = { replaceElement: (el, attrs) => { assert.equal(attrs.type, 'bpmn:ServiceTask'); return replaced; } };
  const modeling = { updateProperties: (el, props) => { updated = { el, props }; } };
  const injector = makeInjector({ elementTemplates: makeElementTemplates(eventBus) });

  new plugin.TemporalTaskModule.temporalReplaceMenuProvider[1](popupMenu, bpmnReplace, modeling, moddle, injector, translate);
  const entries = menu.getPopupMenuEntries(userTask);
  entries['replace-with-temporal-task'].action();

  assert.equal(updated.el, replaced);
  assert.equal(updated.props['camunda:topic'], 'temporal');
  const types = updated.props.extensionElements.values.map((v) => v.$type);
  assert.deepEqual(types, [ 'camunda:ExecutionListener', 'camunda:InputOutput' ]);
});

test('replace menu hides the entry for existing Temporal tasks and non-tasks', () => {
  const moddle = makeModdle();
  let menu;
  new plugin.TemporalTaskModule.temporalReplaceMenuProvider[1](
    { registerProvider: (id, p) => { menu = p; } }, {}, {}, moddle, makeInjector({}), translate);
  const temporal = { businessObject: moddle.create('bpmn:ServiceTask', { 'camunda:type': 'external', 'camunda:topic': 'temporal' }) };
  const gateway = { businessObject: { $type: 'bpmn:ExclusiveGateway', get() {} } };
  assert.deepEqual(menu.getPopupMenuEntries(temporal), {});
  assert.deepEqual(menu.getPopupMenuEntries(gateway), {});
});

test('renderer only takes over Temporal tasks', () => {
  const eventBus = makeEventBus();
  const drawn = [];
  const bpmnRenderer = { drawShape: (gfx, el) => { drawn.push(el); return 'shape'; } };
  new plugin.TemporalTaskModule.temporalRenderer[1](eventBus, bpmnRenderer);
  const plain = { businessObject: makeModdle().create('bpmn:ServiceTask', {}) };
  const results = eventBus.fire('render.shape', { element: plain, gfx: {} });
  assert.deepEqual(results, [ undefined ]);
  assert.equal(drawn.length, 0);
});
