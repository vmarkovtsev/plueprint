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
from weakref import WeakValueDictionary
from markdown.extensions import Extension
from markdown.serializers import ElementTree
from entities import ResourceGroup, Resource, select_pos, \
    SelfParsingSectionRegistry, Action


class APIBlueprintParseError(Exception):
    pass


class APIBlueprint(object):
    def __init__(self):
        super(APIBlueprint, self).__init__()
        self._metadata = {}
        self._name = None
        self._overview = None
        self._groups = OrderedDict()
        self._attributes = WeakValueDictionary()
        self._models = WeakValueDictionary()

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
    def groups(self):
        return self._groups

    def __iter__(self):
        for group in self._groups.values():
            for resource in group:
                yield resource

    def __len__(self):
        return sum(len(g) for g in self._groups.values())

    def __getitem__(self, item):
        return self._groups[item]

    def __str__(self):
        return "APIBlueprint \"%s\", format %s, with %d resources (%d " \
               "actions)" % (
            self.name, self.format, len(self), self.count_actions())

    def count_actions(self):
        return sum(len(r) for r in self)

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
        for item in root[index + 1:]:
            if self._is_header(item) and item.tag <= tag:
                if is_group:
                    self._parse_resource_group(sequence)
                else:
                    try:
                        group = self._groups[None]
                    except KeyError:
                        group = self._groups[None] = ResourceGroup(None, None)
                    self._parse_resource(sequence, group)
                del sequence[:]
                tag = item.tag
                is_group = self._is_group(item)
            sequence.append(item)

    def _parse_resource_group(self, sequence):
        name = sequence[0].text
        name_pos = name.find("Group") + len("Group")
        name = name[name_pos:].strip()
        desc, index = self._parse_description(sequence[1:])
        self._groups[name] = group = ResourceGroup(name, desc)
        if len(sequence) <= index + 1:
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
        rdef = Resource.parse_definition(sequence[0].text)
        desc, index = self._parse_description(sequence[1:])
        rdef += (desc,)
        if len(sequence) <= index + 1:
            return
        if sequence[index].tag in ("ul", "ol"):
            sections = [self._parse_section(s) for s in sequence[index]]
            index += 1
        else:
            sections = tuple()
        kwargs = {s: None for s in Resource.NESTED_SECTIONS}
        kwargs.update({s.NESTED_SECTION_ID: s for s in sections})
        r = Resource(*rdef, **kwargs)
        group.resources[r.id] = r
        if len(sequence) <= index:
            return
        while index < len(sequence) and self._is_header(sequence[index]):
            action = Action.parse_from_etree(*sequence[index:index + 2])
            #r.actions[action.id] = action
            index += 2

    @staticmethod
    def _parse_section(item):
        assert item[0].tag == "p"
        title = item[0].text
        sep_pos = select_pos(title.find(c) for c in (' ', '\t'))
        if sep_pos < 0:
            sep_pos = len(title)
        section_type = title[:sep_pos]
        return SelfParsingSectionRegistry[section_type].prase_from_etree(item)

    @staticmethod
    def _parse_description(sequence):
        index = 0
        desc = ""
        while len(sequence) > index and sequence[index].tag == "p":
            desc += sequence[index].text
            index += 1
        return desc if desc else None, index

    @staticmethod
    def _is_header(item):
        return len(item.tag) == 2 and item.tag[0] == 'h' and \
            item.tag[1].isdigit()

    @classmethod
    def _is_group(cls, item):
        if not cls._is_header(item):
            return False
        return item.text.startswith("Group")


class PlueprintExtension(Extension):
    @staticmethod
    def to_apiblueprint(element):
        return APIBlueprint.parse_from_etree(ElementTree(element))

    def extendMarkdown(self, md, md_globals):
        md.output_formats["apiblueprint"] = self.to_apiblueprint
        md.postprocessors.clear()
        md.stripTopLevelTags = False
