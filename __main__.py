import argparse
import codecs
from markdown import Markdown
import pickle


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-o", "--output", help="Output pickle file path",
                        default=None)
    parser.add_argument("input", help="Input API Blueprint file")
    args = parser.parse_args()
    with codecs.open(args.input, "r", "utf-8") as fin:
        txt = fin.read()
    m = Markdown(extensions=["plueprint"])
    m.set_output_format("apiblueprint")
    api = m.convert(txt)
    if args.output is not None:
        with open(args.output, "wb") as fout:
            pickle.dump(api, fout, protocol=-1)
    else:
        print(api)
        print("Resource groups:")
        for g in api:
            print("  %s" % g)
            print("  Resources:")
            for r in g:
                print("    %s" % r)
                print("    Actions:")
                for a in r:
                    print("      %s" % a)

if __name__ == "__main__":
    main()
