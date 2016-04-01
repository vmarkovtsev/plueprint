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
from copy import deepcopy

from itertools import chain
from collections import OrderedDict, defaultdict
import json
from markdown import to_html_string
import re
from six import add_metaclass, string_types
import sys
from types import GeneratorType
from uritemplate import URITemplate
import weakref
from xml.etree import ElementTree


report_warnings = True

try:
    ustr = unicode
except NameError:
    ustr = str


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
    sep_pos = select_pos(txt.find(c) for c in (' ', '\t', ':'))
    if sep_pos < 0:
        sep_pos = len(txt)
    return txt[:sep_pos]


def get_pre_contents(node):
    cnt = node.text
    if node.tag == "pre" and not cnt and len(node) == 1 and \
            node[0].tag == "code":
        cnt = node[0].text
    return cnt


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


def property_with_parent(name, ptype):
    def getter(self):
        return getattr(self, "_" + name)

    def setter(self, value):
        if value is not None:
            assert isinstance(value, ptype)
            if value.parent is None:
                value._parent = self
        setattr(self, "_" + name, value)

    return property(getter, setter)


class OrderedDefaultDict(OrderedDict, defaultdict):
    def __init__(self, factory, *args, **kwargs):
        super(OrderedDefaultDict, self).__init__(*args, **kwargs)
        self.default_factory = factory


class SelfParsingSectionRegistryDict(type):
    registry = {}

    def __getitem__(cls, item):
        return cls.registry[item]


@add_metaclass(SelfParsingSectionRegistryDict)
class SelfParsingSectionRegistry(type):
    def __init__(cls, what, bases=None, clsdict=None):
        try:
            section_type = clsdict["SECTION_TYPE"]
        except KeyError:
            # base classes
            pass
        else:
            if not isinstance(section_type, (tuple, list, set)):
                section_type = section_type,
            for val in section_type:
                assert val not in SelfParsingSectionRegistry.registry
                SelfParsingSectionRegistry.registry[val] = cls
        super(SelfParsingSectionRegistry, cls).__init__(what, bases, clsdict)


class SmartReprMixin(object):
    def __repr__(self):
        s = str(self)
        if s.startswith(type(self).__name__):
            s = s[len(type(self).__name__):].strip()
        return "%s %s" % (super(SmartReprMixin, self).__repr__(), s)


class Section(SmartReprMixin):
    NESTED_ATTRS = tuple()

    def __init__(self, parent):
        super(Section, self).__init__()
        self._parent = parent

    @property
    def parent(self):
        return self._parent

    @property
    def _parent(self):
        return self.__parent

    @_parent.setter
    def _parent(self, value):
        if value is not None and not isinstance(value, weakref.ProxyType):
            value = weakref.proxy(value)
        self.__parent = value

    def _fix_parents(self, parent):
        self._parent = parent
        for attr in self.NESTED_ATTRS:
            attr = getattr(self, attr)
            if attr is None:
                continue
            if isinstance(attr, Section):
                attr._fix_parents(self)
                continue
            children = getattr(attr, "values", None)
            children = children() if children is not None else attr
            for child in children:
                if isinstance(child, Section):
                    child._fix_parents(self)


class NamedSection(Section):
    def __init__(self, parent, name, description):
        super(NamedSection, self).__init__(parent)
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
    class Base(Section):
        NESTED_ATTRS = "_children",

        def __init__(self, parent, children):
            super(Base, self).__init__(parent)
            self._children = OrderedDict()
            for child in children:
                assert isinstance(child, child_type)
                if child.parent is None:
                    child._parent = self
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
        def parse_from_etree(cls, parent, node):
            if len(node) == 0 or node[0].tag != "ul":
                raise ValueError("Invalid format: %s" % cls.__name__)
            return cls(
                parent,
                (child_type.parse_from_etree(None, c) for c in node[0]))

        def __str__(self):
            return "%s with %d items" % (
                type(self).__name__, len(self._children))

    return Base


class Attribute(NamedSection):
    def __init__(self, parent, name, type_, required, description, value):
        super(Attribute, self).__init__(parent, name, description)
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

    def _fix_parents(self, parent):
        super(Attribute, self)._fix_parents(parent)
        if isinstance(self.value, list):
            for v in self.value:
                if isinstance(v, Attribute):
                    v._fix_parents(self)

    @classmethod
    def parse_from_string(cls, parent, line):
        if line[0] in ('-', '+'):
            line = line[1:]
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
        colon_pos = line.find(':')
        if colon_pos > -1:
            name = line[:colon_pos].strip()
            value = line[colon_pos + 1:].strip() or None
        else:
            name = line
            value = None
        if value is not None:
            try:
                subtype = Attribute.extract_array_subtype(type_)
            except ValueError:
                pass
            else:
                value = [Attribute(None, None, subtype, None, None,
                                   v.split()) for v in value.split(',')]
        instance = cls(parent, name, type_, required, desc, value)
        if isinstance(instance.value, list):
            for child in instance.value:
                if isinstance(child, Attribute):
                    child._parent = instance
        return instance

    @classmethod
    def parse_from_etree(cls, parent, node):
        attr = cls.parse_from_string(parent, node.text)
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
        children = [Attribute.parse_from_etree(attr, c) for c in node[index]]
        attr._value = children
        if attr.is_array:
            subtype = attr.extract_array_subtype(attr.type)
            for c in children:
                if c.type == "object":
                    c._type = subtype
        return attr


class ParameterMember(NamedSection):
    @staticmethod
    def parse_from_string(parent, txt):
        attr = Attribute.parse_from_string(parent, txt)
        return ParameterMember(parent, attr.name, attr.description)

    def __str__(self):
        return "%s - %s" % (self.name, self.description)


class Parameter(Attribute):
    NESTED_ATTRS = Attribute.NESTED_ATTRS + ("_members",)

    def __init__(self, parent, name, type_, required, description, value,
                 default_value, members):
        super(Parameter, self).__init__(
            parent, name, type_, required, description, value)
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

    @classmethod
    def parse_from_etree(cls, parent, node):
        attr = Attribute.parse_from_string(parent, node.text)
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
                    members = [ParameterMember.parse_from_string(None, m.text)
                               for m in li[0]]
        instance = Parameter(
            parent, attr.name, attr.type, attr.required, desc, attr.value,
            defval, members)
        for member in instance.members:
            member._parent = instance
        return instance


class ReferenceableMixin(object):
    def __init__(self, *args, **kwargs):
        super(ReferenceableMixin, self).__init__(*args, **kwargs)
        self._reference = None

    @staticmethod
    def _extract_reference(txt):
        if len(txt) > 4 and txt[0] == "[" and txt.endswith("][]"):
            return txt[1:-3]
        return None


class DataStructure(Attribute, ReferenceableMixin):
    @classmethod
    def parse_from_etree(cls, parent, node):
        instance = super(DataStructure, cls).parse_from_etree(parent, node)
        if len(node) == 1 and node[0].tag in ("p", "pre"):
            reference = cls._extract_reference(get_pre_contents(node[0]))
            if reference is not None:
                instance._description = None
                instance._reference = reference
        return instance


class Parameters(Collection(Parameter)):
    NESTED_SECTION_ID = "parameters"
    SECTION_TYPE = "Parameters", "Parameter"


class Attributes(Collection(Attribute)):
    NESTED_SECTION_ID = "attributes"
    SECTION_TYPE = "Attributes", "Attribute"

    def __init__(self, parent, children, reference=None):
        if reference is not None:
            assert children is None
            children = tuple()
        super(Attributes, self).__init__(parent, children)
        self._reference = reference

    @classmethod
    def parse_from_etree(cls, parent, node):
        try:
            return super(Attributes, cls).parse_from_etree(parent, node)
        except ValueError as e:
            if node.text[-1] == ')':
                br_pos = node.text.rfind('(')
                if br_pos > -1:
                    reference = node.text[br_pos + 1:-1]
                    return Attributes(None, None, reference)
            raise from_none(e)


@add_metaclass(SelfParsingSectionRegistry)
class Headers(Section):
    NESTED_SECTION_ID = "headers"
    SECTION_TYPE = "Headers", "Header"
    NESTED_ATTRS = "_headers",

    def __init__(self, parent, headers):
        super(Headers, self).__init__(parent)
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
    def parse_from_etree(parent, node):
        if len(node) == 0 or node[0].tag not in ("p", "pre"):
            raise ValueError("Invalid headers section format")
        text = get_pre_contents(node[0])
        if text:
            headers = dict(tuple(map(ustr.strip, line.split(':')))
                           for line in text.split('\n') if line)
        else:
            headers = None
        return Headers(parent, headers)


class AssetSection(Section):
    def __init__(self, parent, keyword, content):
        super(AssetSection, self).__init__(parent)
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
    def __init__(self, parent, content):
        super(PredefinedAssetSection, self).__init__(
            parent, self.SECTION_TYPE, content)

    @classmethod
    def parse_from_etree(cls, parent, node):
        if len(node) == 0:
            raise ValueError("Assets section is empty")
        if node[0].tag not in ("pre", "p"):
            raise ValueError("Invalid format of asset section")
        return cls(parent, get_pre_contents(node[0]))


class Body(PredefinedAssetSection):
    NESTED_SECTION_ID = "body"
    SECTION_TYPE = "Body"


class Schema(PredefinedAssetSection):
    NESTED_SECTION_ID = "schema"
    SECTION_TYPE = "Schema"


class PayloadSection(NamedSection):
    NESTED_ATTRS = "_headers", "_attributes", "_body", "_schema", "_reference"

    def __init__(self, parent, keyword, name, media_type, description,
                 headers, attributes, body, schema, reference=None):
        super(PayloadSection, self).__init__(parent, name, description)
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
        self._reference = reference

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

    _headers = property_with_parent("_headers", Headers)
    _attributes = property_with_parent("_attributes", Attributes)
    _body = property_with_parent("_body", Body)
    _schema = property_with_parent("_schema", Schema)

    def value(self):
        if self.media_type == ("application", "json"):
            return json.loads(self.body.content)
        elif self.media_type == ("application", "xml"):
            return ElementTree.fromstring(self.body.content)
        elif self.media_type == ("text", "plain"):
            return self.body.content.strip()
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
    def __init__(self, parent, name, media_type, description,
                 headers, attributes, body, schema):
        super(PredefinedPayloadSection, self).__init__(
            parent, self.SECTION_TYPE, name, media_type, description, headers,
            attributes, body, schema)

    @classmethod
    def parse_from_etree(cls, parent, node):
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
                kwargs["body"] = Body(None, get_pre_contents(node[index]))
            elif node[index].tag == "ul":
                for li in node[index]:
                    section_name = get_section_name(li.text)
                    try:
                        section = SelfParsingSectionRegistry[
                            section_name].parse_from_etree(None, li)
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
        return cls(parent, *defs, **kwargs)

    @staticmethod
    def parse_definition(txt):
        if "\n" in txt:
            if report_warnings:
                sys.stderr.write(
                    "Invalid format, description was discarded: \"%s\"\n"
                    % txt)
            txt = txt[:txt.find("\n")]
        sep_pos = select_pos(txt.find(c) for c in (' ', '\t'))
        if sep_pos < 0:
            return None, None
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


class Model(PredefinedPayloadSection):
    NESTED_SECTION_ID = "model"
    SECTION_TYPE = "Model"


class RRPredefinedPayloadSection(PredefinedPayloadSection, ReferenceableMixin):
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
    def parse_from_etree(cls, parent, node):
        obj = super(RRPredefinedPayloadSection, cls).parse_from_etree(
            parent, node)
        if obj.headers is None and obj.attributes is None and \
                obj.body is None and obj.schema is None and len(node) == 1 \
                and node[0].tag in ("p", "pre"):
            obj._reference = cls._extract_reference(get_pre_contents(node[0]))
        return obj


class Request(RRPredefinedPayloadSection):
    SECTION_TYPE = "Request"
    NESTED_SECTION_ID = "requests"

    def __init__(self, parent, name, media_type, description,
                 headers, attributes, body, schema):
        super(Request, self).__init__(
            parent, name, media_type, description, headers, attributes, body,
            schema)
        self._responses = []

    @property
    def responses(self):
        return {r.http_code: r for r in self._responses}

    @property
    def uri(self):
        values = {}
        for p in chain(self.parent.parent.parameters or tuple(),
                       self.parent.parameters or tuple()):
            if p.default_value is not None:
                values[p.name] = p.default_value
            if p.value is not None:
                values[p.name] = p.value
        return self.uri_template.expand(values)

    def _add_response(self, response):
        assert isinstance(response, Response)
        self._responses.append(weakref.proxy(response))

    def _fix_parents(self, parent):
        super(Request, self)._fix_parents(parent)
        responses = tuple(self._responses)
        del self._responses[:]
        for r in responses:
            self._add_response(self.parent.responses[r.http_code])


class Response(RRPredefinedPayloadSection):
    SECTION_TYPE = "Response"
    NESTED_SECTION_ID = "responses"

    def __init__(self, parent, name, media_type, description,
                 headers, attributes, body, schema):
        super(Response, self).__init__(
            parent, name, media_type, description, headers, attributes, body,
            schema)
        self._request = None

    @property
    def request(self):
        return self._request

    @property
    def _request(self):
        return self.__request

    @_request.setter
    def _request(self, value):
        if value is not None and not isinstance(value, weakref.ProxyType):
            value = weakref.proxy(value)
        self.__request = value

    @property
    def http_code(self):
        return int(self._name)

    def _fix_parents(self, parent):
        super(Response, self)._fix_parents(parent)
        if self.request is not None:
            self._request = self.parent.requests[self.request.name]


class ApiSection(NamedSection):
    NESTED_SECTIONS = "parameters", "attributes"
    URL_PATH_PATH_REGEXP = re.compile("^[\w\-\.]*$]")
    NESTED_ATTRS = "_parameters", "_attributes"

    def __init__(self, parent, name, description, request_method, uri_template,
                 parameters, attributes):
        assert parameters is None or isinstance(parameters, Parameters)
        assert attributes is None or isinstance(attributes, Attributes)
        super(ApiSection, self).__init__(parent, name, description)
        self._request_method = request_method
        self._uri_template = URITemplate(uri_template) \
            if uri_template else None
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

    _parameters = property_with_parent("_parameters", Parameters)
    _attributes = property_with_parent("_attributes", Attributes)

    @property
    def id(self):
        if self.name is not None:
            return self.name
        res = ""
        if self.request_method is not None:
            res += self.request_method + " "
        if self.uri_template is not None:
            res += str(self.uri_template) + " "
        return res.strip()


@add_metaclass(SelfParsingSectionRegistry)
class Relation(Section):
    NESTED_SECTION_ID = "relation"
    SECTION_TYPE = "Relation"

    def __init__(self, parent, link_id):
        super(Relation, self).__init__(parent)
        self._link_id = link_id

    @property
    def link_id(self):
        return self._link_id

    def __str__(self):
        return "Relation " + self._link_id

    @staticmethod
    def parse_from_string(parent, txt):
        txt = txt.strip()
        rel_key = "Relation:"
        if not txt.startswith(rel_key):
            raise ValueError("Invalid format")
        return Relation(parent, txt[len(rel_key):].strip())

    @staticmethod
    def parse_from_etree(parent, node):
        return Relation(parent, node.text.split(":")[-1].strip())


class Action(ApiSection):
    NESTED_SECTIONS = ApiSection.NESTED_SECTIONS + ("relation",)
    NESTED_ATTRS = ApiSection.NESTED_ATTRS + \
        ("_relation", "_requests", "_responses")

    def __init__(self, parent, name, request_method, uri_template, description,
                 relation, parameters, attributes, requests, responses):
        super(Action, self).__init__(parent, name, description, request_method,
                                     uri_template, parameters, attributes)
        if relation is not None:
            assert isinstance(relation, Relation)
        self._relation = relation
        self._requests = OrderedDict()
        index = 0
        for item in requests:
            name = item.name
            if not name:
                name = "#%d" % index
                item._name = name
                index += 1
            self._requests[name] = item
        self._responses = OrderedDefaultDict(list)
        for item in responses:
            code = item.http_code
            if code is None:
                code = 200
            self._responses[code].append(item)
        for r in chain(requests, responses):
            r._parent = self

    @property
    def relation(self):
        return self._relation

    @property
    def requests(self):
        return self._requests

    @property
    def responses(self):
        return self._responses

    @property
    def uri(self):
        values = {}
        for p in chain(self.parent.parameters or tuple(),
                       self.parameters or tuple()):
            if p.default_value is not None:
                values[p.name] = p.default_value
            if p.value is not None:
                values[p.name] = p.value
        return self.uri_template.expand(values)

    _relation = property_with_parent("_relation", Relation)

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
            middle += str(self.uri_template)
        res += middle.strip() + "]"
        return res

    def __iter__(self):
        if not self.requests:
            yield Request(self, "default", None, None, None,
                          self.attributes, None, None), \
                list(chain.from_iterable(self.responses.values()))
        else:
            for request in self.requests.values():
                yield request, request.responses

    def __len__(self):
        if not self.requests:
            return 1
        return len(self.requests)

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
    def parse_from_etree(parent, sequence, index):
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
        current_requests = []
        clear_requests = False
        if len(sequence) > index:
            for li in sequence[index]:
                section_name = get_section_name(li.text)
                try:
                    section = SelfParsingSectionRegistry[
                        section_name].parse_from_etree(None, li)
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
                    if isinstance(section, Request):
                        if clear_requests:
                            del current_requests[:]
                        current_requests.append(section)
                    elif isinstance(section, Response):
                        clear_requests = True
                        for i, cr in enumerate(current_requests):
                            section._request = cr
                            cr._add_response(section)
                            if i < len(current_requests) - 1:
                                kwargs["responses"].append(section)
                                section = deepcopy(section)
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
        return Action(parent, *adef, **kwargs), index


class Resource(ApiSection):
    NESTED_SECTIONS = ApiSection.NESTED_SECTIONS + ("model",)
    NESTED_ATTRS = ApiSection.NESTED_ATTRS + ("_model", "_actions")

    def __init__(self, parent, name, request_method, uri_template, description,
                 parameters, attributes, model):
        assert model is None or isinstance(model, Model)
        super(Resource, self).__init__(
            parent, name, description, request_method, uri_template,
            parameters, attributes)
        self._model = model
        self._actions = OrderedDict()

    @property
    def model(self):
        return self._model

    @property
    def uri(self):
        values = {}
        for p in self.parameters or tuple():
            if p.default_value is not None:
                values[p.name] = p.default_value
            if p.value is not None:
                values[p.name] = p.value
        return self.uri_template.expand(values)

    _model = property_with_parent("_model", Model)

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
            middle += str(self.uri_template)
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
    NESTED_ATTRS = "_resources",

    def __init__(self, parent, name, description):
        super(ResourceGroup, self).__init__(parent, name, description)
        self._resources = OrderedDict()

    def __getitem__(self, item):
        return self._resources[item]

    def __iter__(self):
        for resource in self._resources.values():
            yield resource

    def __len__(self):
        return len(self._resources)

    def __str__(self):
        return "ResourceGroup with %d resources (%d actions)" % (
            len(self), sum(len(r) for r in self)
        )

    def print_resources(self):
        for r in self:
            print(r)
