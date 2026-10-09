"""Strict, versioned, read-only business tool registry."""
from dataclasses import dataclass
from rest_framework.exceptions import ValidationError


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    handler: object
    properties: dict
    required: tuple = ()

    def definition(self):
        return {'type': 'function', 'function': {'name': self.name, 'description': self.description,
                'parameters': {'type': 'object', 'properties': self.properties,
                               'required': list(self.required), 'additionalProperties': False}}}


_REGISTRY = {}


def register(name, description, properties=None, required=()):
    def wrap(func):
        if name in _REGISTRY:
            raise RuntimeError(f'Duplicate AI tool: {name}')
        _REGISTRY[name] = Tool(name, description, func, properties or {}, tuple(required))
        return func
    return wrap


def definitions():
    return [tool.definition() for tool in _REGISTRY.values()]


def tool_names():
    return sorted(_REGISTRY)


def invoke(name, user, arguments):
    tool = _REGISTRY.get(name)
    if not tool:
        raise ValidationError({'tool': 'Unknown or disabled tool.'})
    if not isinstance(arguments, dict):
        raise ValidationError({'arguments': 'Expected a JSON object.'})
    unknown = set(arguments) - set(tool.properties)
    if unknown:
        raise ValidationError({'arguments': f'Unsupported parameters: {", ".join(sorted(unknown))}'})
    missing = set(tool.required) - set(arguments)
    if missing:
        raise ValidationError({'arguments': f'Missing parameters: {", ".join(sorted(missing))}'})
    for key, value in arguments.items():
        prop = tool.properties[key]
        typ = prop['type']
        if typ == 'integer' and (isinstance(value, bool) or not isinstance(value, int)):
            raise ValidationError({key: 'Expected an integer.'})
        if typ == 'string' and not isinstance(value, str):
            raise ValidationError({key: 'Expected a string.'})
        if typ == 'boolean' and not isinstance(value, bool):
            raise ValidationError({key: 'Expected a boolean.'})
        if 'enum' in prop and value not in prop['enum']:
            raise ValidationError({key: 'Unsupported value.'})
        if typ == 'integer' and not prop.get('minimum', -10**9) <= value <= prop.get('maximum', 10**9):
            raise ValidationError({key: 'Out of allowed range.'})
        if typ == 'string' and len(value) > prop.get('maxLength', 160):
            raise ValidationError({key: 'Value too long.'})
    return tool.handler(user=user, **arguments)


S = lambda description, max_len=160: {'type': 'string', 'description': description, 'maxLength': max_len}
I = lambda description, minimum=1, maximum=100: {'type': 'integer', 'description': description,
                                                  'minimum': minimum, 'maximum': maximum}
E = lambda description, choices: {'type': 'string', 'description': description, 'enum': list(choices)}
DATES = {'date_from': S('Inclusive date YYYY-MM-DD', 10), 'date_to': S('Inclusive date YYYY-MM-DD', 10)}
FILTERS = {**DATES, 'company_id': S('Company UUID; cannot expand logged-in visibility', 36),
           'branch_id': S('Branch UUID; cannot expand logged-in visibility', 36), 'team_id': S('Team UUID, when explicitly selected', 36),
           'project_name': S('Exact project name, when requested'),
           'agent_user': S('Dialer agent username. Prefer agent_user over name.'),
           'dialer_id': S('Exact dialer UUID from list_visible_dialers, not a project', 36)}
