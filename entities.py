"""
API Blueprint (https://github.com/apiaryio/api-blueprint) parser which uses
Markdown (https://pythonhosted.org/Markdown/).

Released under New BSD License.

Copyright © 2015, Vadim Markovtsev :: AO InvestGroup
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:
    * Redistributions of source code must retain the above copyright
      notice, this list of conditions and the following disclaimer.
    * Redistributions in binary form must reproduce the above copyright
      notice, this list of conditions and the following disclaimer in the
      documentation and/or other materials provided with the distribution.
    * Neither the name of the AO InvestGroup nor the
      names of its contributors may be used to endorse or promote products
      derived from this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL VADIM MARKOVTSEV BE LIABLE FOR ANY
DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
(INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
"""


from collections import OrderedDict
import json
from six import add_metaclass
from types import GeneratorType
from xml.etree import ElementTree


def select_pos(*args):
    pos = 100500
    if len(args) == 1 and isinstance(args[0], GeneratorType):
        args = args[0]
    for arg in args:
        if -1 < arg < pos:
            pos = arg
    if pos == 100500:
        pos = -1
    return pos


class SelfParsingSectionRegistryDict(type):
    registry = {}

    def __getitem__(cls, item):
        return cls.registry[item]


@add_metaclass(SelfParsingSectionRegistryDict)
class SelfParsingSectionRegistry(type):
    def __init__(cls, what, bases=None, clsdict=None):
        try:
            SelfParsingSectionRegistry.registry[clsdict["SECTION_TYPE"]] = cls
        except KeyError:
            pass
        super(SelfParsingSectionRegistry, cls).__init__(what, bases, clsdict)


class NamedSection(object):
    def __init__(self, name, description):
        super(NamedSection, self).__init__()
        self._name = name
        self._description = description

    @property
    def name(self):
        return self._name

    @property
    def description(self):
        return self._description


class ResourceGroup(NamedSection):
    def __init__(self, name, description):
        super(ResourceGroup, self).__init__(name, description)
        self._resources = OrderedDict()

    @property
    def resources(self):
        return self._resources

    def __iter__(self):
        for resource in self._resources.values():
            yield resource

    def __len__(self):
        return len(self._resources)


def Collection(child_type):
    @add_metaclass(SelfParsingSectionRegistry)
    class Base(object):
        def __init__(self, children):
            super(Collection, self).__init__()
            self._children = OrderedDict()
            for child in children:
                assert isinstance(child, child_type)
                self._children[child.name] = child
            self.__dict__.update(self._children)

        def __iter__(self):
            for child in self._children.values():
                yield child

        def __len__(self):
            return len(self._children)

        def __getitem__(self, item):
            return self._children[item]

    return Base


class Attribute(object):
    def __init__(self, name, type_, required, description, value):
        super(Attribute, self).__init__()
        self._name = name
        self._type = type_
        self._required = required
        self._description = description
        self._value = value

    @property
    def name(self):
        return self._name

    @property
    def type(self):
        return self._type

    @property
    def required(self):
        return self._required

    @property
    def description(self):
        return self._description

    @property
    def value(self):
        return self._value

    @staticmethod
    def parse_from_string(txt):
        lines = txt.strip().split('\n')
        line = lines[0]
        if line[0] in ('-', '+'):
            line = line[1:]
        colon_pos = line.find(':')
        if colon_pos > -1:
            name = line[:colon_pos].strip()
            line = line[colon_pos + 1:]
        else:
            sep_pos = select_pos(line.find(c) for c in (' ', '\t'))
            if sep_pos > -1:
                name = line[:sep_pos].strip()
            else:
                raise ValueError("Invalid format")
        desc_pos = line.rfind('-')
        if desc_pos > -1:
            desc = line[desc_pos + 1:].strip()
            line = line[:desc_pos].strip()
        else:
            desc = None
        if line[-1] == ')':
            type_pos = line.rfind('(')
            if type_pos < 0:
                raise ValueError("Invalid type format")
            type_ = line[type_pos + 1:-1].strip()
            req_pos = type_.rfind(',')
            if req_pos > -1:
                word = type_[req_pos + 1:].strip()
                required = word == "required"
                if not required and word == "optional":
                    required = False
            else:
                required = None
            line = line[:type_pos].strip()
        else:
            type_ = None
            required = None
        if len(lines) == 1:
            value = line if line else None
        else:
            value_object = OrderedDict()
            value_list = []
            for line in lines[1:]:
                attr = Attribute.parse_from_string(line)
                if attr.name is None:
                    value_list.append(attr)
                else:
                    value_object[attr.name] = attr
            if len(value_list) > 0 and len(value_object) > 0:
                raise ValueError("Invalid format")
            value = value_list if value_list else value_object
        return Attribute(name, type_, required, desc, value)

    def __str__(self):
        res = self.name
        if self.value is not None:
            res += ": " + self.value
        if self.type is not None:
            res += " (" + self.type
            if isinstance(self.required, bool):
                res += ", " + ("optional", "required")[self.required]
            res += ")"
        if self.description is not None:
            res += " - " + self.description
        return res


class ParameterMember(object):
    def __init__(self, name, description):
        self._name = name
        self._description = description

    @property
    def name(self):
        return self._name

    @property
    def description(self):
        return self._description

    @staticmethod
    def parse_from_string(txt):
        attr = Attribute.parse_from_string(txt)
        return ParameterMember(attr.name, attr.description)


class Parameter(Attribute):
    def __init__(self, name, type_, required, description, value,
                 default_value, members):
        super(Parameter, self).__init__(name, type_, required, description,
                                        value)
        self._default_value = default_value
        if members is not None:
            assert isinstance(members, (tuple, list))
        self._members = tuple(members)

    @property
    def default_value(self):
        return self._default_value

    @property
    def members(self):
        return self._members


class Parameters(Collection(Parameter)):
    NESTED_SECTION_ID = "parameters"

    @staticmethod
    def parse_from_etree(node):
        return None


class Attributes(Collection(Attribute)):
    NESTED_SECTION_ID = "attributes"

    @staticmethod
    def parse_from_etree(node):
        return None


class Headers(object):
    def __init__(self, headers):
        super(Headers, self).__init__()
        self._headers = OrderedDict(headers)

    def __iter__(self):
        for p in self._headers.items():
            yield p

    def __len__(self):
        return len(self._headers)

    def __getitem__(self, item):
        return self._headers[item]

    def keys(self):
        return self._headers.keys()

    def values(self):
        return self._headers.values()

    def __str__(self):
        return "\n".join("%s: %s" % p for p in self)


class AssetSection(object):
    def __init__(self, keyword, content):
        super(AssetSection, self).__init__()
        self._keyword = keyword
        self._content = content

    @property
    def keyword(self):
        return self._keyword

    @property
    def content(self):
        return self._content

    def __str__(self):
        return "%s\n%s" % (self.keyword, self.content)


@add_metaclass(SelfParsingSectionRegistry)
class PredefinedAssetSection(AssetSection):
    def __init__(self, content):
        super(PredefinedAssetSection, self).__init__(
            self.SECTION_TYPE, content)

    @staticmethod
    def parse_from_etree(node):
        return None


class Body(PredefinedAssetSection):
    SECTION_TYPE = "Body"


class Schema(PredefinedAssetSection):
    SECTION_TYPE = "Schema"


class PayloadSection(NamedSection):
    def __init__(self, keyword, name, media_type, description,
                 headers, attributes, body, schema):
        super(PayloadSection, self).__init__(name, description)
        self._keyword = keyword
        if media_type is not None:
            assert isinstance(media_type, (tuple, list))
        if headers is not None:
            assert isinstance(headers, Headers)
        if body is not None:
            assert isinstance(body, Body)
        if schema is not None:
            assert isinstance(schema, Schema)
        self._media_type = tuple(media_type)
        self._headers = headers
        self._attributes = attributes
        self._body = body
        self._schema = schema

    @property
    def keyword(self):
        return self._keyword

    @property
    def media_type(self):
        return self._media_type

    @property
    def headers(self):
        return self._headers

    @property
    def attributes(self):
        return self._attributes

    @property
    def body(self):
        return self._body

    @property
    def schema(self):
        return self._schema

    def value(self):
        if self.media_type == ("application", "json"):
            return json.loads(self.body)
        elif self.media_type == ("application", "xml"):
            return ElementTree.fromstring(self.body)
        raise NotImplemented(
            "value() is not implemented for media type %s/%s" %
            self.media_type)

    def __str__(self):
        res = "%s %s" % (self.keyword, self.name)
        if self.media_type is not None:
            res += " (%s/%s)" % self.media_type
        return res

    @staticmethod
    def parse_definition(txt):
        txt = txt.strip()
        if txt[-1] == ')':
            br_pos = txt.rfind('(')
            if br_pos < 0:
                raise ValueError("Invalid format")
            mt = txt[br_pos + 1:-1].split('/')
            txt = txt[:br_pos].strip()
        else:
            mt = None
        sep_pos = select_pos(txt.find(c) for c in (' ', '\t'))
        if sep_pos < 0:
            raise ValueError("Invalid format: no keyword")
        keyword = txt[:sep_pos]
        name = txt[sep_pos + 1:].strip()
        return keyword, name, mt


@add_metaclass(SelfParsingSectionRegistry)
class PredefinedPayloadSection(PayloadSection):
    def __init__(self, name, media_type, description,
                 headers, attributes, body, schema):
        super(PredefinedPayloadSection, self).__init__(
            self.SECTION_TYPE, name, media_type, description, headers,
            attributes, body, schema)

    @staticmethod
    def parse_from_etree(node):
        return None


class ResourceModel(PredefinedPayloadSection):
    NESTED_SECTION_ID = "model"
    SECTION_TYPE = "Model"


class ApiSection(NamedSection):
    NESTED_SECTIONS = "parameters", "attributes"

    def __init__(self, name, description, request_method, uri_template,
                 parameters, attributes):
        assert parameters is None or isinstance(parameters, Parameters)
        assert attributes is None or isinstance(attributes, Attributes)
        super(ApiSection, self).__init__(name, description)
        self._request_method = request_method
        self._uri_template = uri_template
        self._parameters = parameters
        self._attributes = attributes

    @property
    def request_method(self):
        return self._request_method

    @property
    def uri_template(self):
        return self._uri_template

    @property
    def parameters(self):
        return self._parameters

    @property
    def attributes(self):
        return self._attributes

    @property
    def id(self):
        if self.name is not None:
            return self.name
        if self.uri_template is not None:
            return self.uri_template
        return self.request_method


@add_metaclass(SelfParsingSectionRegistry)
class Relation(object):
    NESTED_SECTION_ID = "relation"
    SECTION_TYPE = "Relation"

    def __init__(self, link_id):
        super(Relation, self).__init__()
        self._link_id = link_id

    @property
    def link_id(self):
        return self._link_id

    def __str__(self):
        return "Relation: " + self._link_id

    @staticmethod
    def parse_from_string(txt):
        txt = txt.strip()
        rel_key = "Relation:"
        if not txt.startswith(rel_key):
            raise ValueError("Invalid format")
        return Relation(txt[len(rel_key):].strip())

    @staticmethod
    def parse_from_etree(node):
        return None


class Request(PredefinedPayloadSection):
    SECTION_TYPE = "Request"


class Response(PredefinedPayloadSection):
    SECTION_TYPE = "Response"


class Action(ApiSection):
    NESTED_SECTIONS = ApiSection.NESTED_SECTIONS + ("relation",)

    def __init__(self, name, request_method, uri_template, description,
                 relation, parameters, attributes):
        super(Action, self).__init__(name, description, request_method,
                                     uri_template, parameters, attributes)
        if relation is not None:
            assert isinstance(relation, Relation)
        self._relation = relation
        self._requests = OrderedDict()
        self._responses = OrderedDict()

    @property
    def relation(self):
        return self._relation

    @property
    def requests(self):
        return self._requests

    @property
    def responses(self):
        return self._responses

    def __str__(self):
        res = "Action "
        if self.name is None:
            res += self.request_method
            return res
        res += self.name
        bpe = self.request_method is not None or self.uri_template is not None
        if bpe:
            res += " ["
        middle = ""
        if self.request_method is not None:
            middle += self.request_method + " "
        if self.uri_template is not None:
            middle += self.uri_template
        res += middle.strip() + "]"
        return res

    @staticmethod
    def parse_from_etree(node_def, node_list):
        return None


class Resource(ApiSection):
    NESTED_SECTIONS = ApiSection.NESTED_SECTIONS + ("model",)

    def __init__(self, name, request_method, uri_template, description,
                 parameters, attributes, model):
        assert model is None or isinstance(model, ResourceModel)
        super(Resource, self).__init__(name, description, request_method,
                                       uri_template, parameters, attributes)
        self._model = model
        self._actions = OrderedDict()

    @property
    def actions(self):
        return self._actions

    @property
    def model(self):
        return self._model

    def __iter__(self):
        for action in self.actions:
            yield action

    def __len__(self):
        return len(self.actions)

    def __getitem__(self, item):
        return self.actions[item]

    def __str__(self):
        res = "Resource "
        bpe = self.request_method is not None or self.uri_template is not None
        if self.name is not None:
            res += self.name + " "
            if bpe:
                res += "["
        middle = ""
        if self.request_method is not None:
            middle += self.request_method + " "
        if self.uri_template is not None:
            middle += self.uri_template
        res += middle.strip()
        if bpe:
            res += ']'
        return res

    @staticmethod
    def parse_definition(txt):
        txt = txt.strip()
        if txt[-1] == ']':
            br_pos = txt.rfind('[')
            if br_pos < 0:
                raise ValueError("Invalid format")
            part = txt[br_pos + 1:-1].strip()
            sep_pos = select_pos(part.find(c) for c in (' ', '\t'))
            if sep_pos > -1:
                method = part[:sep_pos]
                template = part[sep_pos:].strip()
            else:
                method = None
                template = part
            name = txt[:br_pos]
        else:
            name = None
            sep_pos = select_pos(txt.find(c) for c in (' ', '\t'))
            if sep_pos > -1:
                method = txt[:sep_pos]
                if method not in ("GET", "POST", "PUT", "PATCH", "DELETE",
                                  "HEAD"):
                    method = None
                    template = txt
                else:
                    template = txt[sep_pos + 1:].strip()
            else:
                method = None
                template = txt
        return name, method, template
