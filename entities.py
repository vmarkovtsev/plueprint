# -*- coding: utf-8 -*-
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
from markdown import to_html_string
import re
from six import add_metaclass, string_types
import sys
from types import GeneratorType
from xml.etree import ElementTree


report_warnings = True


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


def get_section_name(txt):
    if txt is None:
        return None
    sep_pos = select_pos(txt.find(c) for c in (' ', '\t'))
    if sep_pos < 0:
        sep_pos = len(txt)
    return txt[:sep_pos]


def parse_description(sequence, index, *stop_tags):
    desc = ""
    while len(sequence) > index and sequence[index].tag not in stop_tags:
        desc += to_html_string(sequence[index]) + "\n"
        index += 1
    return desc.strip() if desc else None, index


def from_none(exc):
    """Emulates raise ... from None (PEP 409) on older Python-s
    """
    try:
        exc.__cause__ = None
    except AttributeError:
        exc.__context__ = None
    return exc


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


def Collection(child_type):
    @add_metaclass(SelfParsingSectionRegistry)
    class Base(object):
        def __init__(self, children):
            super(Base, self).__init__()
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

        @classmethod
        def parse_from_etree(cls, node):
            if len(node) == 0 or node[0].tag != "ul":
                raise ValueError("Invalid format: %s" % cls.__name__)
            return cls(child_type.parse_from_etree(c) for c in node[0])

    return Base


class Attribute(NamedSection):
    def __init__(self, name, type_, required, description, value):
        super(Attribute, self).__init__(name, description)
        self._type = type_ or "object"
        self._required = required
        self._description = description
        self._value = value

    @property
    def type(self):
        return self._type

    @property
    def required(self):
        return self._required

    @property
    def value(self):
        return self._value

    @property
    def is_array(self):
        return self.type.startswith("array")

    @staticmethod
    def extract_array_subtype(type_):
        if type_ is None or not type_.startswith("array"):
            raise ValueError("Type %s is not an array type" % type_)
        subtype = type_[len("array"):]
        if subtype:
            if subtype[0] != '[' or subtype[-1] != ']':
                raise ValueError("Invalid type format: %s")
            subtype = subtype[1:-1]
        else:
            subtype = "object"
        return subtype

    @staticmethod
    def parse_from_string(line):
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
                line = line[sep_pos + 1:].strip()
            else:
                raise ValueError("Invalid format")
        desc_pos = line.rfind('-')
        if desc_pos > -1:
            desc = line[desc_pos + 1:].strip()
            line = line[:desc_pos].strip()
        else:
            desc = None
        if line and line[-1] == ')':
            type_pos = line.rfind('(')
            if type_pos < 0:
                raise ValueError("Invalid type format")
            type_ = line[type_pos + 1:-1].strip()
            req_pos = type_.rfind(',')
            if req_pos > -1:
                word = type_[req_pos + 1:].strip()
                type_ = type_[:req_pos].strip()
                required = word == "required"
                if not required and word == "optional":
                    required = False
            else:
                required = None
            line = line[:type_pos].strip()
        else:
            type_ = None
            required = None
        value = line if line else None
        if value is not None:
            try:
                subtype = Attribute.extract_array_subtype(type_)
            except ValueError:
                pass
            else:
                value = [Attribute(None, subtype, None, None, v.split())
                         for v in value.split(',')]
        return Attribute(name, type_, required, desc, value)

    def __str__(self):
        res = self.name
        if self.value is not None:
            multivalue = not isinstance(self.value, string_types)
            if not multivalue:
                res += ": " + self.value
        else:
            multivalue = False
        if self.type is not None:
            res += " (" + self.type
            if isinstance(self.required, bool):
                res += ", " + ("optional", "required")[self.required]
            res += ")"
        if self.description is not None:
            res += " - " + self.description.replace('\n', ' ')
        if multivalue:
            res += "\n"
            for v in self.value:
                for line in str(v).split('\n'):
                    res += "  %s\n" % line
        return res

    @staticmethod
    def parse_from_etree(node):
        attr = Attribute.parse_from_string(node.text)
        desc, index = parse_description(node, 0, "ul")
        if attr._description is None:
            attr._description = desc
        elif desc is not None:
            attr._description += "\n" + desc
        if len(node) <= index:
            return attr
        if attr.value is not None:
            raise ValueError("Multiple value for the same attribute %s" %
                             attr.name)
        children = [Attribute.parse_from_etree(c) for c in node[index]]
        attr._value = children
        if attr.is_array:
            subtype = attr.extract_array_subtype(attr.type)
            for c in children:
                if c.type == "object":
                    c._type = subtype
        return attr


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
        else:
            self._members = tuple()

    @property
    def default_value(self):
        return self._default_value

    @property
    def members(self):
        return self._members

    @staticmethod
    def parse_from_etree(node):
        attr = Attribute.parse_from_string(node.text)
        desc, index = parse_description(node, 0, "ul")
        if attr.description is None:
            attr._description = desc
        elif desc is not None:
            attr._description += "\n" + desc
        defval = None
        members = None
        if len(node) > index:
            for li in node[index]:
                if li.text.startswith("Default"):
                    if attr.required or attr.required is None:
                        raise ValueError(
                            "Default value was specified for a non-optional "
                            "parameter %s" % attr.name)
                    sep_pos = li.text.find(':')
                    if sep_pos < 0:
                        raise ValueError("Invalid format")
                    defval = li.text[sep_pos + 1:].strip()
                elif li.text.startswith("Members"):
                    if len(li) == 0 or li[0].tag != "ul":
                        raise ValueError("Invalid format: %s" % attr.name)
                    members = [ParameterMember.parse_from_string(m.text)
                               for m in li[0]]
        return Parameter(attr.name, attr.type, attr.required, desc, attr.value,
                         defval, members)


class Parameters(Collection(Parameter)):
    NESTED_SECTION_ID = "parameters"
    SECTION_TYPE = "Parameters"


class Attributes(Collection(Attribute)):
    NESTED_SECTION_ID = "attributes"
    SECTION_TYPE = "Attributes"

    def __init__(self, children, reference=None):
        if reference is not None:
            assert children is None
            children = tuple()
        super(Attributes, self).__init__(children)
        self._reference = reference

    @property
    def reference(self):
        return self._reference

    @classmethod
    def parse_from_etree(cls, node):
        try:
            return super(Attributes, cls).parse_from_etree(node)
        except ValueError as e:
            if node.text[-1] == ')':
                br_pos = node.text.rfind('(')
                if br_pos > -1:
                    reference = node.text[br_pos + 1:-1]
                    return Attributes(None, reference)
            raise from_none(e)


@add_metaclass(SelfParsingSectionRegistry)
class Headers(object):
    NESTED_SECTION_ID = "headers"
    SECTION_TYPE = "Headers"

    def __init__(self, headers):
        super(Headers, self).__init__()
        self._headers = OrderedDict(headers) if headers else OrderedDict()

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

    @staticmethod
    def parse_from_etree(node):
        if len(node) == 0 or node[0].tag not in ("p", "pre"):
            raise ValueError("Invalid headers section format")
        if node[0].text:
            headers = dict(tuple(map(str.strip, line.split(':')))
                           for line in node[0].text.split('\n'))
        else:
            headers = None
        return Headers(headers)


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

    @classmethod
    def parse_from_etree(cls, node):
        if len(node) == 0:
            raise ValueError("Assets section is empty")
        if node[0].tag not in ("pre", "p"):
            raise ValueError("Invalid format of asset section")
        return cls(node[0].text)


class Body(PredefinedAssetSection):
    NESTED_SECTION_ID = "body"
    SECTION_TYPE = "Body"


class Schema(PredefinedAssetSection):
    NESTED_SECTION_ID = "schema"
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
        self._media_type = \
            tuple(media_type) if media_type is not None else None
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
        res = "%s%s" % (self.keyword, (" " + self.name) if self.name else "")
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

    @classmethod
    def parse_from_etree(cls, node):
        defs = cls.parse_definition(node.text)
        desc, index = parse_description(node, 0, "pre", "ul")
        defs += desc,
        kwargs = {
            "headers": None,
            "attributes": None,
            "body": None,
            "schema": None
        }
        if len(node) > index:
            if node[index].tag == "pre":
                kwargs["body"] = Body(node[index].text)
            elif node[index].tag == "ul":
                for li in node[index]:
                    section_name = get_section_name(li.text)
                    try:
                        section = SelfParsingSectionRegistry[
                            section_name].parse_from_etree(li)
                    except KeyError:
                        if report_warnings:
                            sys.stderr.write(
                                "Section \"%s\" is unknown\n" % section_name)
                    except ValueError as e:
                        if report_warnings:
                            sys.stderr.write(
                                "Failed to parse section \"%s\" in payload "
                                "section %s: %s\n" % (
                                    section_name, defs[0], e))
                    else:
                        kwargs[section.NESTED_SECTION_ID] = section
        return cls(*defs, **kwargs)

    @staticmethod
    def parse_definition(txt):
        sep_pos = select_pos(txt.find(c) for c in (' ', '\t'))
        if sep_pos < 0:
            raise ValueError("Invalid payload section format")
        txt = txt[sep_pos + 1:].strip()
        if not txt:
            return None, None
        if txt[-1] == ')':
            br_pos = txt.rfind('(')
            if br_pos < 0:
                raise ValueError("Invalid payload section format")
            media_type = txt[br_pos + 1:-1].strip().split("/")
            if br_pos > 0:
                name = txt[:br_pos - 1]
            else:
                name = None
        else:
            name = txt
            media_type = None
        return name, media_type


class ResourceModel(PredefinedPayloadSection):
    NESTED_SECTION_ID = "model"
    SECTION_TYPE = "Model"


class ReferenceablePredefinedPayloadSection(PredefinedPayloadSection):
    def __init__(self, name, media_type, description,
                 headers, attributes, body, schema):
        super(ReferenceablePredefinedPayloadSection, self).__init__(
            name, media_type, description, headers, attributes, body, schema)
        self._reference = None

    def _copy_from_payload(self, payload):
        if self.name is None:
            self._name = payload.name
        self._description = payload.description
        self._media_type = payload.media_type
        self._headers = payload.headers
        self._attributes = payload.attributes
        self._body = payload.body
        self._schema = payload.schema

    @classmethod
    def parse_from_etree(cls, node):
        obj = super(ReferenceablePredefinedPayloadSection, cls) \
            .parse_from_etree(node)
        if obj.headers is None and obj.attributes is None and \
                obj.body is None and obj.schema is None and len(node) == 1 \
                and node[0].tag in ("p", "pre"):
            obj._reference = cls._extract_reference(node[0].text)
        return obj

    @staticmethod
    def _extract_reference(txt):
        if len(txt) > 4 and txt[0] == "[" and txt.endswith("][]"):
            return txt[1:-3]
        return None


class Request(ReferenceablePredefinedPayloadSection):
    SECTION_TYPE = "Request"
    NESTED_SECTION_ID = "requests"


class Response(ReferenceablePredefinedPayloadSection):
    SECTION_TYPE = "Response"
    NESTED_SECTION_ID = "responses"

    @property
    def http_code(self):
        return self._name


class ApiSection(NamedSection):
    NESTED_SECTIONS = "parameters", "attributes"
    URL_PATH_PATH_REGEXP = re.compile("^[\w\-\.]*$]")

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
    def const_uri(self):
        if self.uri_template is None:
            return None
        parts = self.uri_template.split('/')
        const_parts = []
        for p in parts:
            if not self.URL_PATH_PATH_REGEXP.match(p):
                break
            const_parts.append(p)
        return "/" + "/".join(const_parts)

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
        res = ""
        if self.request_method is not None:
            res += self.request_method + " "
        if self.uri_template is not None:
            res += self.uri_template + " "
        return res.strip()

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
        return Relation(node.text.split(":")[-1].strip())


class Action(ApiSection):
    NESTED_SECTIONS = ApiSection.NESTED_SECTIONS + ("relation",)

    def __init__(self, name, request_method, uri_template, description,
                 relation, parameters, attributes, requests, responses):
        super(Action, self).__init__(name, description, request_method,
                                     uri_template, parameters, attributes)
        if relation is not None:
            assert isinstance(relation, Relation)
        self._relation = relation
        index = [0]

        def iter_r(rs):
            for r in rs:
                if not r.name:
                    yield str(index[0]), r
                    index[0] += 1
                else:
                    yield r.name, r

        self._requests = OrderedDict(iter_r(requests))
        index = [0]
        self._responses = OrderedDict(iter_r(responses))

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
                method = part
                template = None
            name = txt[:br_pos].strip()
        else:
            name = None
            method = txt
            template = None
        return name, method, template

    @staticmethod
    def parse_from_etree(sequence, index):
        adef = Action.parse_definition(sequence[index].text)
        desc, index = parse_description(sequence, index + 1, "ul")
        kwargs = {
            "description": desc,
            "relation": None,
            "parameters": None,
            "attributes": None,
            "requests": [],
            "responses": []
        }
        if len(sequence) > index:
            for li in sequence[index]:
                section_name = get_section_name(li.text)
                try:
                    section = SelfParsingSectionRegistry[
                        section_name].parse_from_etree(li)
                except KeyError:
                    if report_warnings:
                        sys.stderr.write(
                            "Section \"%s\" is unknown\n" % section_name)
                except ValueError as e:
                    if report_warnings:
                        sys.stderr.write(
                            "Failed to parse section \"%s\" in action "
                            "%s: %s\n" % (section_name, adef[0], e))
                else:
                    if section.SECTION_TYPE in ("Request", "Response"):
                        kwargs[section.NESTED_SECTION_ID].append(section)
                    else:
                        kwargs[section.NESTED_SECTION_ID] = section
            index += 1
        # This section may include one nested Attributes section defining the
        # input (request) attributes of the section. If present, these
        # attributes should be inherited in every Action's Request section
        # unless specified otherwise.
        for req in kwargs["requests"]:
            if req.attributes is None:
                req._attributes = kwargs["attributes"]
        return Action(*adef, **kwargs), index


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
    def model(self):
        return self._model

    def __iter__(self):
        for action in self._actions.values():
            yield action

    def __len__(self):
        return len(self._actions)

    def __getitem__(self, item):
        return self._actions[item]

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
        if self.name is not None and bpe:
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
            name = txt[:br_pos].strip()
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


class ResourceGroup(NamedSection):
    def __init__(self, name, description):
        super(ResourceGroup, self).__init__(name, description)
        self._resources = OrderedDict()

    def __getitem__(self, item):
        return self._resources[item]

    def __iter__(self):
        for resource in self._resources.values():
            yield resource

    def __len__(self):
        return len(self._resources)

    def __str__(self):
        return "Resource group with %d resources (%d actions)" % (
            len(self), sum(len(r) for r in self)
        )

    def print_resources(self):
        for r in self:
            print(r)
