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
from collections import OrderedDict, defaultdict
from copy import deepcopy
from itertools import chain
import sys

from markdown.preprocessors import Preprocessor
from markdown.treeprocessors import Treeprocessor
from markdown.extensions import Extension
from markdown.serializers import ElementTree, to_html_string
from pytrie import SortedStringTrie as trie
from .entities import ResourceGroup, Resource, SelfParsingSectionRegistry, \
    Action, DataStructure, Section, get_section_name, parse_description, \
    Attributes, SmartReprMixin
from . import entities


class APIBlueprintParseError(Exception):
    pass


class APIBlueprint(SmartReprMixin):
    def __init__(self):
        super(APIBlueprint, self).__init__()
        self._metadata = {}
        self._name = None
        self._overview = None
        self._groups = OrderedDict()
        self._trie = trie()
        self._data_structures = OrderedDict()

        def strip():
            del self.strip
            return self

        # trick Markdown in the end of the conversion
        self.strip = strip

    @property
    def metadata(self):
        return self._metadata

    @property
    def format(self):
        return self._metadata.get("FORMAT")

    @property
    def name(self):
        return self._name

    @property
    def overview(self):
        return self._overview

    @property
    def resources(self):
        for g in self:
            for r in g:
                yield r

    @property
    def actions(self):
        for r in self.resources:
            for a in r:
                yield a

    def __iter__(self):
        for group in self._groups.values():
            yield group

    def __len__(self):
        return len(self._groups)

    def __getitem__(self, item):
        if item:
            if item[0] == ">":
                path = item[1:].split(">")
                if path[0]:
                    group = self._groups[path[0]]
                else:
                    group = self._groups[None]
                if len(path) == 1:
                    return group
                resource = group[path[1]]
                if len(path) == 2:
                    return resource
                action = resource[path[2]]
                return action
            elif item[0] == "/":
                cpos = item.find(":")
                if ":" in item:
                    method = item[cpos + 1:]
                    item = item[:cpos]
                else:
                    method = None
                if item[-1] == "/" and len(item) > 1:
                    item = item[:-1]
                values = self._trie.longest_prefix_value(item)
                if method is None:
                    return tuple(chain.from_iterable(values.values()))
                return values[method]
        return self._groups[item]

    def __str__(self):
        return "APIBlueprint \"%s\", format %s, with %d resource groups (%d " \
               "resources, %d actions)" % (
                self.name, self.format, len(self), self.count_resources(),
                self.count_actions())

    def keys(self):
        return self._groups.keys()

    def values(self):
        return self._groups.values()

    def count_resources(self):
        return sum(len(g) for g in self)

    def count_actions(self):
        return sum(sum(len(r) for r in g) for g in self)

    def merge(self, other):
        if not isinstance(other, APIBlueprint):
            raise TypeError("Merge with plueprint.mdparser.APIBlueprint "
                            "objects only")
        if other.name:
            self._name += " & " + other.name
        if other.overview:
            self._overview += "\n" + other.overview
        if set(self._data_structures).intersection(other._data_structures):
            raise ValueError("Data structures collide")
        self._data_structures.update(deepcopy(other._data_structures))
        for group in other:
            mineg = self._groups.get(group.name)
            if mineg is None:
                mineg = self._groups[group.name] = deepcopy(group)
            else:
                for resource in group:
                    miner = mineg._resources.get(resource.id)
                    if miner is None:
                        mineg._resources[resource.id] = deepcopy(resource)
                    else:
                        for action in resource:
                            minea = miner._actions.get(action.id)
                            if minea is not None:
                                raise NotImplementedError(
                                    "Cannot merge actions: %s" % minea)
                            miner[action.id] = deepcopy(action)
            mineg._parent = self
            mineg._fix_parents(self)
        self._reset_trie()

    @staticmethod
    def parse_from_etree(tree):
        instance = APIBlueprint()
        instance._parse(tree.getroot())
        return instance

    def _parse(self, root):
        if len(root) < 3:
            raise APIBlueprintParseError("Invalid document format")
        if root[0].tag != "p":
            raise APIBlueprintParseError("Empty or missing metadata section")
        for line in root[0].text.split('\n'):
            colon_pos = line.index(':')
            if colon_pos < 1:
                raise APIBlueprintParseError("Invalid metadata format")
            self._metadata[line[:colon_pos]] = line[colon_pos + 1:].strip()
        if root[1].tag != "h1":
            raise APIBlueprintParseError("Invalid or missing name section")
        self._name = root[1].text
        index = 2
        self._overview, index = parse_description(root, index, "h1")
        self._attributes = {}
        self._models = {}
        try:
            current = root[index]
            sequence = [current]
            tag = current.tag
            is_group = self._is_group(current)
            is_data_structures = self._is_data_structures(current)
            for item in root[index + 1:]:
                if self._is_header(item) and item.tag <= tag:
                    if is_group:
                        self._parse_resource_group(sequence)
                    else:
                        self._parse_resource(sequence, None)
                    del sequence[:]
                    tag = item.tag
                    is_group = self._is_group(item)
                    if not is_group:
                        is_data_structures = self._is_data_structures(item)
                sequence.append(item)
            if is_group:
                self._parse_resource_group(sequence)
            elif is_data_structures:
                self._parse_data_structure(sequence)
            else:
                self._parse_resource(sequence, None)
            self._reset_trie()
            self._apply_attributes_references()
        finally:
            del self._attributes
            del self._models

    def _reset_trie(self):
        paths = defaultdict(lambda: defaultdict(list))
        for a in self.actions:
            cu = a.uri
            if cu is not None:
                path = ""
                paths["/"][a.request_method].append(a)
                for sub in cu.split('/'):
                    if sub:
                        path += "/" + sub
                        paths[path][a.request_method].append(a)
        self._trie = trie(paths.items())

    def _parse_resource_group(self, sequence):
        name = sequence[0].text
        name_pos = name.find("Group") + len("Group")
        name = name[name_pos:].strip()
        desc, index = parse_description(sequence, 1, "h2")
        self._groups[name] = group = ResourceGroup(self, name, desc)
        if len(sequence) <= index:
            return
        current = sequence[index]
        children = [current]
        tag = current.tag
        for item in sequence[index + 1:]:
            if self._is_header(item) and item.tag <= tag:
                self._parse_resource(children, group)
                del children[:]
                tag = item.tag
            children.append(item)
        if len(children) > 0:
            self._parse_resource(children, group)

    def _parse_resource(self, sequence, group):
        if group is None:
            try:
                group = self._groups[None]
            except KeyError:
                group = self._groups[None] = ResourceGroup(self, None, None)
        rdef = Resource.parse_definition(sequence[0].text)
        desc, index = parse_description(
            sequence, 1, self._next_header_tag(sequence[0].tag), "ul")
        if len(sequence) <= index:
            if entities.report_warnings:
                sys.stderr.write("Skipping empty resource %s\n" % rdef[0])
            return
        desc_sections = False
        if sequence[index].tag in ("ul", "ol"):
            sections = []
            for s in sequence[index]:
                section = self._parse_section(None, s, rdef[0])
                if section is not None:
                    sections.append(section)
                else:
                    if desc is None:
                        desc = "<ul>\n"
                    desc += to_html_string(s) + "\n"
                    desc_sections = True
            index += 1
        else:
            sections = tuple()
        if desc_sections:
            desc += "</ul>"
        rdef += (desc,)
        kwargs = {s: None for s in Resource.NESTED_SECTIONS}
        kwargs.update({s.NESTED_SECTION_ID: s for s in sections})
        action_instead_of_resource = False
        try:
            r = Resource(group, *rdef, **kwargs)
        except TypeError as e:
            action_instead_of_resource = True
            r = Resource(group, *rdef, parameters=None, attributes=None,
                         model=None)
            if entities.report_warnings:
                sys.stderr.write("Invalid section in resource %s: %s\n" %
                                 (r, e))
        else:
            if r.model is not None and r.name is not None:
                self._models[r.name] = r.model
        group._resources[r.id] = r
        if r.attributes is not None and r.name is not None:
            self._attributes[r.name] = r.attributes
        if len(sequence) <= index:
            if action_instead_of_resource:
                try:
                    act, _ = Action.parse_from_etree(r, sequence, 0)
                    act._name = r.name
                    act._request_method = r.request_method
                    act._uri_template = r.uri_template
                    r._actions[act.id] = act
                    if entities.report_warnings:
                        sys.stderr.write(
                            "Assumed single implicit action in %s\n" % r)
                except:
                    pass
            return
        while index < len(sequence) and self._is_header(sequence[index]):
            action, index = Action.parse_from_etree(r, sequence, index)
            if action.uri_template is None:
                action._uri_template = r.uri_template
            if action.request_method is None:
                action._request_method = r.request_method
            for rr in chain(action.requests.values(),
                            chain.from_iterable(action.responses.values())):
                if rr._reference is None:
                    continue
                if rr._reference not in self._models:
                    if entities.report_warnings:
                        sys.stderr.write("Bad reference: %s\n" %
                                         rr._reference)
                else:
                    rr._copy_from_payload(self._models[rr._reference])
            r._actions[action.id] = action

    def _parse_data_structure(self, sequence):
        index = 1
        while index < len(sequence):
            node = sequence[index]
            index += 1
            while index < len(sequence) and \
                    not self._is_header(sequence[index]):
                node.append(sequence[index])
                index += 1
            attr = DataStructure.parse_from_etree(self, node)
            self._data_structures[attr.name] = attr

    def _apply_attributes_references(self):
        for key, attr in self._data_structures.items():
            ref = attr._reference
            if ref is not None:
                self._data_structures[key] = attr = self._attributes.get(ref)
                if attr is None and entities.report_warnings:
                    sys.stderr.write("Invalid attributes reference in Data "
                                     "Structures: %s\n" % ref)
        for r in self.resources:
            oldattr = r.attributes
            if oldattr is not None and oldattr._reference is not None:
                r._attributes = self._attributes.get(
                    oldattr._reference,
                    self._data_structures.get(oldattr._reference))
                if r.attributes is None and entities.report_warnings:
                    sys.stderr.write("Invalid attributes reference: %s\n" %
                                     oldattr._reference)
            for a in r:
                if a.attributes is oldattr:
                    a._attributes = r.attributes
                elif a.attributes is not None and \
                        a.attributes._reference is not None:
                    ref = a.attributes._reference
                    aval = self._attributes.get(ref)
                    if aval is not None:
                        a._attributes = aval
                        continue
                    dsval = self._data_structures.get(ref)
                    if dsval is not None:
                        a._attributes = Attributes(a, dsval.value)
                    if a.attributes is None and entities.report_warnings:
                        sys.stderr.write("Invalid attributes reference: %s\n"
                                         % ref)

    @staticmethod
    def _parse_section(parent, item, name):
        section_name = get_section_name(item.text)
        try:
            return SelfParsingSectionRegistry[section_name].parse_from_etree(
                parent, item)
        except KeyError:
            if entities.report_warnings:
                sys.stderr.write(
                    "Section \"%s\" is unknown\n" % section_name)
        except ValueError as e:
            if entities.report_warnings:
                sys.stderr.write(
                    "Failed to parse section \"%s\" in resource "
                    "%s: %s\n" % (section_name, name, e))
        return None

    @staticmethod
    def _is_header(item):
        return len(item.tag) == 2 and item.tag[0] == 'h' and \
            item.tag[1].isdigit()

    @staticmethod
    def _next_header_tag(tag):
        return "%s%d" % (tag[0], (int(tag[1]) + 1))

    @classmethod
    def _is_group(cls, item):
        if not cls._is_header(item):
            return False
        return item.text.startswith("Group")

    @classmethod
    def _is_data_structures(cls, item):
        if not cls._is_header(item):
            return False
        return item.text == "Data Structures"


class BackQuotesRemover(Preprocessor):
    def run(self, lines):
        return [line.replace('`', '') for line in lines]


class IndentationAligner(Preprocessor):
    def run(self, lines):
        new_lines = []
        for line in lines:
            if line:
                i = 0
                while i < len(line) and line[i] == ' ':
                    i += 1
                if i > 0 and i % 4:
                    line = ' ' * (i + (4 - (i % 4))) + line[i:]
            new_lines.append(line)
        return new_lines


class TitleLifter(Treeprocessor):
    def run(self, root):
        lifo = [root]
        while lifo:
            last = lifo.pop()
            if len(lifo) > 0 and last.text == "\n" and len(last) > 0 and \
                    last[0].tag == "p":
                last.text = last[0].text
                last.remove(last[0])
            lifo.extend(last)
        h1_count = sum(1 for item in root
                       if item.tag == "h1" and item.text != "Data Structures")
        if h1_count != 1:
            return
        if entities.report_warnings:
            sys.stderr.write("There is only one <h1> in the document => "
                             "raising all the other headers\n")
        for item in root:
            tag = item.tag
            if tag == "h1":
                if item.text == "Data Structures":
                    break
                else:
                    continue
            if len(tag) != 2 or tag[0] != "h" or not tag[1].isdigit():
                continue
            item.tag = "h%d" % (int(tag[1]) - 1)


class PlueprintExtension(Extension):
    @staticmethod
    def to_apiblueprint(element):
        return APIBlueprint.parse_from_etree(ElementTree(element))

    def extendMarkdown(self, md, md_globals):
        md.output_formats["apiblueprint"] = self.to_apiblueprint
        md.preprocessors["remove_backquotes"] = BackQuotesRemover(md)
        md.preprocessors["align_indent"] = IndentationAligner(md)
        md.treeprocessors["lift_title"] = TitleLifter(md)
        md.postprocessors.clear()
        md.stripTopLevelTags = False
