import sys

from distutils.core import setup
from setuptools.command.test import test as TestCommand  # noqa


class Tox(TestCommand):
    def finalize_options(self):
        TestCommand.finalize_options(self)
        self.test_args = []
        self.test_suite = True

    def run_tests(self):
        import tox
        errno = tox.cmdline(self.test_args)
        sys.exit(errno)


setup(
    name='django-conditional-aggregates',
    version='0.1.0',
    packages=['aggregates'],
    license='MIT',
    long_description=open('README.rst').read(),
    description=(
        'Django aggregate functions which operate conditionally (i.e. generate'
        ' SQL `CASE` statements)'
    ),
    author='Anentropic',
    author_email='ego@anentropic.com',
    url='https://github.com/anentropic/django-conditional-aggregates',
    install_requires=[],
    tests_require=[
        'tox',
        'pytest-django',
        'py>=1.4.25',  # seems bug in py.test, needs this lib
    ],
    cmdclass={'test': Tox},
)
