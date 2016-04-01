from setuptools import setup
import os


def parse_requirements():
    with open(os.path.join(os.path.dirname(__file__),
                           "requirements.txt"), "r") as fin:
        return fin.read().split("\n")


setup(
    name="plueprint",
    description="API Blueprint (https://apiblueprint.org/) parser in pure "
                "Python",
    version="0.4.2",
    license="New BSD",
    author="Vadim Markovtsev",
    author_email="gmarkhor@gmail.com",
    url="https://github.com/vmarkovtsev/plueprint",
    download_url='https://github.com/vmarkovtsev/plueprint',
    packages=["plueprint"],
    package_dir={"plueprint": "."},
    keywords=["blueprint", "apiblueprint"],
    install_requires=parse_requirements(),
    package_data={'': ['requirements.txt', 'LICENSE', 'README.md']},
    classifiers=[
        "Development Status :: 4 - Beta",
        "Environment :: Console",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: BSD License",
        "Operating System :: POSIX",
        "Programming Language :: Python :: 2.7",
        "Programming Language :: Python :: 3.2",
        "Programming Language :: Python :: 3.3",
        "Programming Language :: Python :: 3.4",
        "Topic :: Software Development :: Libraries"
    ]
)
