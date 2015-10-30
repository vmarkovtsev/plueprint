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

import codecs
import os
import sys

from markdown import Markdown

root = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
if root not in sys.path:
    sys.path.insert(0, root)


def main():
    m = Markdown(extensions=["plueprint"])
    m.set_output_format("apiblueprint")
    tests_dir = os.path.join(os.path.dirname(__file__), "api-blueprint",
                             "examples")
    skip_number = 0
    index = 0
    for doc in sorted(os.listdir(tests_dir)):
        if os.path.splitext(doc)[1] != ".md" or doc == "README.md":
            continue
        index += 1
        if index <= skip_number:
            continue
        with codecs.open(os.path.join(tests_dir, doc), "r", "utf-8") as fin:
            txt = fin.read()
        api = m.convert(txt)
        print("-- %s --" % doc)
        print(api)
        try:
            api[">"].print_resources()
        except KeyError:
            pass
        print("Actions:")
        for action in api["/"]:
            print(action)

if __name__ == "__main__":
    main()
