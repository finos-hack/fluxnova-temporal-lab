/**
 * Fluxnova "Temporal task" — a bpmn-js module shared by the web designer and
 * the Fluxnova Modeler desktop plugin.
 *
 * A Temporal task is a BPMN service task implemented as an external task on
 * topic "temporal". Its input parameters tell the Fluxnova -> Temporal bridge
 * which workflow to start. The module adds:
 *
 *   - a palette entry "Create Temporal task"
 *   - a "Temporal task" entry in the change-type (replace) menu of tasks
 *   - a Temporal badge on those tasks
 *   - an element template, so the properties panel shows a "Temporal workflow"
 *     form instead of raw input parameters
 *
 * Plain ES5 with no imports: services are injected by bpmn-js, so the same
 * file runs in the browser bundle and inside the desktop Modeler.
 */
(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = api;
  } else {
    root.FluxnovaTemporalTask = api;
  }
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var TEMPLATE_ID = 'org.finos.fluxnova.temporal.TemporalTask';
  var TOPIC = 'temporal';
  var ACCENT = '#5B4BDB';

  var ICON_SVG =
    '<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 22 22">' +
    '<rect x="1.5" y="3.5" width="19" height="15" rx="3" fill="none" stroke="#22242a" stroke-width="1.5"/>' +
    '<circle cx="15.5" cy="7.5" r="4.5" fill="' + ACCENT + '"/>' +
    '<path d="M13.6 6h3.8M15.5 6v3.6" stroke="#fff" stroke-width="1.3" stroke-linecap="round"/>' +
    '</svg>';

  var ICON_URL = 'data:image/svg+xml;utf8,' + encodeURIComponent(ICON_SVG);

  /**
   * Default input parameters. Keep in sync with TEMPLATE below and with
   * bridge/fluxnova_temporal_bridge/mapping.py.
   */
  var DEFAULT_INPUTS = [
    { name: 'temporalWorkflowType', value: '' },
    { name: 'temporalTaskQueue', value: '' },
    { name: 'temporalWorkflowId', value: '${execution.processBusinessKey}:${execution.currentActivityId}' },
    { name: 'temporalInputVariables', value: '' },
    { name: 'temporalResultVariable', value: 'temporalResult' },
    { name: 'temporalErrorCode', value: 'TEMPORAL_WORKFLOW_FAILED' }
  ];

  var TEMPLATE = {
    $schema: 'https://unpkg.com/@camunda/element-templates-json-schema/resources/schema.json',
    name: 'Temporal task',
    id: TEMPLATE_ID,
    description: 'Runs this task as a Temporal workflow and waits for its result',
    documentationRef: 'https://docs.temporal.io/workflows',
    appliesTo: [ 'bpmn:ServiceTask' ],
    groups: [
      { id: 'workflow', label: 'Temporal workflow' },
      { id: 'data', label: 'Data' },
      { id: 'errors', label: 'Errors' }
    ],
    properties: [
      {
        type: 'Hidden',
        value: 'external',
        binding: { type: 'property', name: 'camunda:type' }
      },
      {
        type: 'Hidden',
        value: TOPIC,
        binding: { type: 'property', name: 'camunda:topic' }
      },
      {
        label: 'Workflow type',
        description: 'Name of the Temporal workflow to start, e.g. DocumentChecksWorkflow',
        type: 'String',
        group: 'workflow',
        binding: { type: 'camunda:inputParameter', name: 'temporalWorkflowType' },
        constraints: { notEmpty: true }
      },
      {
        label: 'Task queue',
        description: 'Task queue polled by the Temporal worker',
        type: 'String',
        group: 'workflow',
        binding: { type: 'camunda:inputParameter', name: 'temporalTaskQueue' },
        constraints: { notEmpty: true }
      },
      {
        label: 'Workflow ID',
        description: 'Correlates the process and the workflow. A retried task re-attaches to the same workflow instead of starting a new one.',
        type: 'String',
        group: 'workflow',
        value: '${execution.processBusinessKey}:${execution.currentActivityId}',
        binding: { type: 'camunda:inputParameter', name: 'temporalWorkflowId' }
      },
      {
        label: 'Input variables',
        description: 'Comma-separated process variables sent to the workflow as one JSON object. Empty sends all variables.',
        type: 'String',
        group: 'data',
        binding: { type: 'camunda:inputParameter', name: 'temporalInputVariables' }
      },
      {
        label: 'Result variable',
        description: 'An object result is merged into the process variables; any other result is stored in this variable.',
        type: 'String',
        group: 'data',
        value: 'temporalResult',
        binding: { type: 'camunda:inputParameter', name: 'temporalResultVariable' }
      },
      {
        label: 'BPMN error code',
        description: 'Thrown when the workflow fails. A workflow can choose its own code by raising ApplicationError(message, "CODE", type="BpmnError").',
        type: 'String',
        group: 'errors',
        value: 'TEMPORAL_WORKFLOW_FAILED',
        binding: { type: 'camunda:inputParameter', name: 'temporalErrorCode' }
      }
    ]
  };

  // ---------------------------------------------------------------------------
  // helpers

  var PREFIXES = [ 'camunda', 'fluxnova' ];

  function getBusinessObject(element) {
    return (element && element.businessObject) || element;
  }

  function getAttr(bo, localName) {
    if (!bo) {
      return undefined;
    }
    for (var i = 0; i < PREFIXES.length; i++) {
      try {
        var value = bo.get(PREFIXES[i] + ':' + localName);
        if (value !== undefined) {
          return value;
        }
      } catch (e) {
        // prefix not registered in this modeler
      }
    }
    return bo.$attrs && (bo.$attrs['camunda:' + localName] || bo.$attrs['fluxnova:' + localName]);
  }

  function isTemporalTask(element) {
    var bo = getBusinessObject(element);
    if (!bo || bo.$type !== 'bpmn:ServiceTask') {
      return false;
    }
    if (getAttr(bo, 'modelerTemplate') === TEMPLATE_ID) {
      return true;
    }
    return getAttr(bo, 'type') === 'external' && getAttr(bo, 'topic') === TOPIC;
  }

  function extensionPrefix(moddle) {
    for (var i = 0; i < PREFIXES.length; i++) {
      try {
        if (moddle.getType(PREFIXES[i] + ':InputOutput')) {
          return PREFIXES[i];
        }
      } catch (e) {
        // not registered
      }
    }
    throw new Error('Temporal task plugin: no camunda or fluxnova moddle extension found');
  }

  /**
   * Build the business object properties that make a service task a
   * Temporal task. Existing extension elements other than input/output
   * mappings are kept.
   */
  function buildTemporalProperties(moddle, existingExtensionElements) {
    var prefix = extensionPrefix(moddle);

    var inputs = DEFAULT_INPUTS.map(function (input) {
      return moddle.create(prefix + ':InputParameter', { name: input.name, value: input.value });
    });
    var inputOutput = moddle.create(prefix + ':InputOutput', { inputParameters: inputs });
    inputs.forEach(function (input) { input.$parent = inputOutput; });

    var kept = ((existingExtensionElements && existingExtensionElements.get('values')) || [])
      .filter(function (value) { return !/:InputOutput$/.test(value.$type); });

    var extensionElements = moddle.create('bpmn:ExtensionElements', {
      values: kept.concat([ inputOutput ])
    });
    extensionElements.get('values').forEach(function (value) { value.$parent = extensionElements; });

    var properties = { extensionElements: extensionElements };
    properties[prefix + ':type'] = 'external';
    properties[prefix + ':topic'] = TOPIC;
    properties[prefix + ':modelerTemplate'] = TEMPLATE_ID;
    return properties;
  }

  function registerTemplate(injector) {
    var elementTemplates = injector.get('elementTemplates', false);
    if (!elementTemplates || elementTemplates.get(TEMPLATE_ID)) {
      return;
    }
    elementTemplates.set(elementTemplates.getAll().concat([ TEMPLATE ]));
  }

  // ---------------------------------------------------------------------------
  // template registration

  function TemporalTemplateRegistrar(eventBus, injector) {
    registerTemplate(injector);
    // Template loaders replace the template list on (re)load; add ours back.
    eventBus.on([ 'import.done', 'elementTemplates.changed' ], function () {
      registerTemplate(injector);
    });
  }
  TemporalTemplateRegistrar.$inject = [ 'eventBus', 'injector' ];

  // ---------------------------------------------------------------------------
  // palette

  function TemporalPaletteProvider(palette, create, elementFactory, moddle, injector, translate) {
    this._create = create;
    this._elementFactory = elementFactory;
    this._moddle = moddle;
    this._injector = injector;
    this._translate = translate || function (text) { return text; };
    palette.registerProvider(this);
  }
  TemporalPaletteProvider.$inject = [
    'palette', 'create', 'elementFactory', 'moddle', 'injector', 'translate'
  ];

  TemporalPaletteProvider.prototype.createTemporalTaskShape = function () {
    registerTemplate(this._injector);

    var businessObject = this._moddle.create('bpmn:ServiceTask', { name: 'Temporal task' });
    var properties = buildTemporalProperties(this._moddle);
    Object.keys(properties).forEach(function (key) {
      businessObject.set(key, properties[key]);
    });
    businessObject.extensionElements.$parent = businessObject;

    return this._elementFactory.createShape({
      type: 'bpmn:ServiceTask',
      businessObject: businessObject
    });
  };

  TemporalPaletteProvider.prototype.getPaletteEntries = function () {
    var self = this;

    function start(event) {
      self._create.start(event, self.createTemporalTaskShape());
    }

    return {
      'create.temporal-task': {
        group: 'activity',
        className: 'fluxnova-temporal-palette-entry',
        imageUrl: ICON_URL,
        title: this._translate('Create Temporal task'),
        action: { dragstart: start, click: start }
      }
    };
  };

  // ---------------------------------------------------------------------------
  // replace (change type) menu

  function TemporalReplaceMenuProvider(popupMenu, bpmnReplace, modeling, moddle, injector, translate) {
    this._bpmnReplace = bpmnReplace;
    this._modeling = modeling;
    this._moddle = moddle;
    this._injector = injector;
    this._translate = translate || function (text) { return text; };
    popupMenu.registerProvider('bpmn-replace', this);
  }
  TemporalReplaceMenuProvider.$inject = [
    'popupMenu', 'bpmnReplace', 'modeling', 'moddle', 'injector', 'translate'
  ];

  var REPLACEABLE = [
    'bpmn:Task', 'bpmn:ServiceTask', 'bpmn:UserTask', 'bpmn:ScriptTask',
    'bpmn:SendTask', 'bpmn:ReceiveTask', 'bpmn:ManualTask', 'bpmn:BusinessRuleTask'
  ];

  TemporalReplaceMenuProvider.prototype.getPopupMenuEntries = function (target) {
    var self = this;
    var bo = getBusinessObject(target);

    if (!bo || REPLACEABLE.indexOf(bo.$type) === -1 || isTemporalTask(target)) {
      return {};
    }

    return {
      'replace-with-temporal-task': {
        label: this._translate('Temporal task'),
        imageUrl: ICON_URL,
        className: 'fluxnova-temporal-replace-entry',
        action: function () {
          self.makeTemporalTask(target);
        }
      }
    };
  };

  TemporalReplaceMenuProvider.prototype.makeTemporalTask = function (element) {
    registerTemplate(this._injector);

    var newElement = getBusinessObject(element).$type === 'bpmn:ServiceTask'
      ? element
      : this._bpmnReplace.replaceElement(element, { type: 'bpmn:ServiceTask' });

    var bo = getBusinessObject(newElement);
    var properties = buildTemporalProperties(this._moddle, bo.extensionElements);
    // Drop other implementations so the external task settings win.
    [ 'class', 'expression', 'delegateExpression', 'resultVariable' ].forEach(function (name) {
      if (getAttr(bo, name) !== undefined) {
        properties[extensionPrefix(this._moddle) + ':' + name] = undefined;
      }
    }, this);

    this._modeling.updateProperties(newElement, properties);
    return newElement;
  };

  // ---------------------------------------------------------------------------
  // rendering: Temporal badge on the task

  var SVG_NS = 'http://www.w3.org/2000/svg';

  function svg(tag, attrs) {
    var node = document.createElementNS(SVG_NS, tag);
    Object.keys(attrs).forEach(function (key) { node.setAttribute(key, attrs[key]); });
    return node;
  }

  function drawBadge(parentGfx, element) {
    var group = svg('g', { 'class': 'fluxnova-temporal-badge' });
    var cx = element.width - 14;
    group.appendChild(svg('circle', { cx: cx, cy: 14, r: 8, fill: ACCENT }));
    group.appendChild(svg('path', {
      d: 'M' + (cx - 4) + ' 11h8M' + cx + ' 11v7',
      stroke: '#fff',
      'stroke-width': 1.6,
      'stroke-linecap': 'round',
      fill: 'none'
    }));
    var title = svg('title', {});
    title.textContent = 'Temporal workflow';
    group.appendChild(title);
    parentGfx.appendChild(group);
  }

  function TemporalRenderer(eventBus, bpmnRenderer) {
    eventBus.on('render.shape', 1500, function (event, context) {
      var element = context.element;
      if (!isTemporalTask(element)) {
        return;
      }
      var shape = bpmnRenderer.drawShape(context.gfx, element, context.attrs);
      drawBadge(context.gfx, element);
      return shape;
    });
  }
  TemporalRenderer.$inject = [ 'eventBus', 'bpmnRenderer' ];

  // ---------------------------------------------------------------------------

  var TemporalTaskModule = {
    __init__: [
      'temporalTemplateRegistrar',
      'temporalPaletteProvider',
      'temporalReplaceMenuProvider',
      'temporalRenderer'
    ],
    temporalTemplateRegistrar: [ 'type', TemporalTemplateRegistrar ],
    temporalPaletteProvider: [ 'type', TemporalPaletteProvider ],
    temporalReplaceMenuProvider: [ 'type', TemporalReplaceMenuProvider ],
    temporalRenderer: [ 'type', TemporalRenderer ]
  };

  return {
    TEMPLATE: TEMPLATE,
    TEMPLATE_ID: TEMPLATE_ID,
    TOPIC: TOPIC,
    ICON_URL: ICON_URL,
    DEFAULT_INPUTS: DEFAULT_INPUTS,
    TemporalTaskModule: TemporalTaskModule,
    isTemporalTask: isTemporalTask,
    buildTemporalProperties: buildTemporalProperties
  };
});
