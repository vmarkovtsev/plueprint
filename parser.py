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
from itertools import chain
import sys

from collections import OrderedDict, defaultdict
from markdown.preprocessors import Preprocessor
from markdown.treeprocessors import Treeprocessor
from weakref import WeakValueDictionary
from markdown.extensions import Extension
from markdown.serializers import ElementTree
from pytrie import SortedStringTrie as trie
from .entities import ResourceGroup, Resource, select_pos, \
    SelfParsingSectionRegistry, Action, Attribute, get_section_name, \
    parse_description
from . import entities


class APIBlueprintParseError(Exception):
    pass


class APIBlueprint(object):
    def __init__(self):
        super(APIBlueprint, self).__init__()
        self._metadata = {}
        self._name = None
        self._overview = None
        self._groups = OrderedDict()
        self._trie = trie()
        self._attributes = WeakValueDictionary()
        self._models = WeakValueDictionary()
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
        return self._metadata["FORMAT"]

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
                if item[-1] == "/":
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

    def count_resources(self):
        return sum(len(g) for g in self)

    def count_actions(self):
        return sum(sum(len(r) for r in g) for g in self)

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
        if root[2].tag == "p":
            self._overview = root[2].text
            index = 3
        else:
            index = 2
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
            self._parse_data_structures(sequence)
        else:
            self._parse_resource(sequence, None)
        paths = defaultdict(lambda: defaultdict(list))
        for a in self.actions:
            cu = a.const_uri
            if cu is not None:
                paths[cu][a.request_method].append(a)
        self._trie = trie(paths.items())
        self._apply_attributes_references()
        self._apply_model_reference()

    def _parse_resource_group(self, sequence):
        name = sequence[0].text
        name_pos = name.find("Group") + len("Group")
        name = name[name_pos:].strip()
        desc, index = parse_description(sequence, 1)
        self._groups[name] = group = ResourceGroup(name, desc)
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

    def _parse_resource(self, sequence, group):
        if group is None:
            try:
                group = self._groups[None]
            except KeyError:
                group = self._groups[None] = ResourceGroup(None, None)
        rdef = Resource.parse_definition(sequence[0].text)
        desc, index = parse_description(sequence, 1)
        rdef += (desc,)
        if len(sequence) <= index:
            return
        if sequence[index].tag in ("ul", "ol"):
            sections = []
            for s in sequence[index]:
                section = self._parse_section(s, rdef[0])
                if section is not None:
                    sections.append(section)
            index += 1
        else:
            sections = tuple()
        kwargs = {s: None for s in Resource.NESTED_SECTIONS}
        kwargs.update({s.NESTED_SECTION_ID: s for s in sections})
        r = Resource(*rdef, **kwargs)
        group._resources[r.id] = r
        if r.attributes is not None and r.name is not None:
            self._attributes[r.name] = r.attributes
        if len(sequence) <= index:
            return
        while index < len(sequence) and self._is_header(sequence[index]):
            action, index = Action.parse_from_etree(sequence, index)
            if action.uri_template is None:
                action._uri_template = r.uri_template
            if action.request_method is None:
                action._request_method = r.request_method
            r._actions[action.id] = action

    def _parse_data_structures(self, sequence):
        index = 1
        while index < len(sequence):
            node = sequence[index]
            index += 1
            if index >= len(sequence) or sequence[index].tag != "ul":
                raise ValueError("Invalid format of data structures")
            node.append(sequence[index])
            index += 1
            attr = Attribute.parse_from_etree(node)
            self._data_structures[attr.name] = attr

    def _apply_attributes_references(self):
        for r in self.resources:
            oldattr = r.attributes
            if oldattr is not None and oldattr.reference is not None:
                r._attributes = self._attributes[oldattr.reference]
            for a in r:
                if a.attributes is oldattr:
                    a._attributes = r.attributes
                elif a.attributes is not None and \
                        a.attributes.reference is not None:
                    a._attributes = self._attributes[a.attributes.reference]

    def _apply_model_reference(self):
        pass

    @staticmethod
    def _parse_section(item, name):
        section_name = get_section_name(item.text)
        try:
            return SelfParsingSectionRegistry[section_name].parse_from_etree(
                item)
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
                while line[i] == ' ':
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
