from distutils.core import setup


setup(
    name='django-conditional-aggregates',
    version='0.5.0',
    packages=['djconnagg'],
    license='MIT',
    long_description=open('README.rst').read(),
    description=(
        'Django aggregate functions which operate conditionally (i.e. generate'
        ' SQL `CASE WHEN` statements)'
    ),
    author='Anentropic',
    author_email='ego@anentropic.com',
    url='https://github.com/anentropic/django-conditional-aggregates',
    install_requires=[],
)
