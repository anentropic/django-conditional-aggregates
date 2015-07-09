=============================
django-conditional-aggregates
=============================

|Build Status| |PyPi Version|

|Python2.7|

|Django1.6| |Django1.7|

.. |Build Status| image:: https://travis-ci.org/anentropic/django-conditional-aggregates.svg?branch=master
    :alt: Build Status
    :target: https://travis-ci.org/anentropic/django-conditional-aggregates
.. |PyPi Version| image:: https://badge.fury.io/py/django-conditional-aggregates.svg
    :alt: Latest PyPI version
    :target: https://pypi.python.org/pypi/django-conditional-aggregates/
.. |Python2.7| image:: https://img.shields.io/badge/Python%202.7--brightgreen.svg
    :alt: Python 2.7
.. |Django1.6| image:: https://img.shields.io/badge/Django%201.6--brightgreen.svg
    :alt: Django 1.6
.. |Django1.7| image:: https://img.shields.io/badge/Django%201.7--brightgreen.svg
    :alt: Django 1.7


*(Django 1.4 and 1.5 are not possible due to limitation of older `SQLCompiler` class)*

Note: from Django 1.8 on this module is not needed as support is built-in:  
https://docs.djangoproject.com/en/1.8/ref/models/conditional-expressions/#case

Sometimes you need some conditional logic to decide which related rows to 'aggregate' in your aggregation function.

In SQL you can do this with a ``CASE`` clause, for example:

.. code:: sql

    SELECT
        stats_stat.campaign_id,
        SUM(
            CASE WHEN (
                stats_stat.stat_type = a
                AND stats_stat.event_type = v
            )
            THEN stats_stat.count
            ELSE 0
            END
        ) AS impressions
    FROM stats_stat
    GROUP BY stats_stat.campaign_id

Note this is different to doing Django's normal ``.filter(...).aggregate(Sum(...))`` ...what we're doing is effectively inside the ``Sum(...)`` part of the ORM.

I believe these 'conditional aggregates' are most (perhaps *only*) useful when doing a ``GROUP BY`` type of query - they allow you to control exactly how the values in the group get aggregated, for example to only sum up rows matching certain criteria.


Usage:

``pip install django-conditional-aggregates``

.. code:: python

    from django.db.models import Q
    from djconnagg import ConditionalSum

    # recreate the SQL example from above in pure Django ORM:
    report = (
        Stat.objects
            .values('campaign_id')  # values + annotate => GROUP BY
            .annotate(
                impressions=ConditionalSum(
                    'count',
                    when=Q(stat_type='a', event_type='v')
                ),
            )
    )

Note that standard Django ``Q`` objects are used to formulate the ``CASE WHEN(...)`` clause. Just like in the rest of the ORM, you can combine them with ``() | & ~`` operators to make a complex query.

``ConditionalSum`` and ``ConditionalCount`` aggregate functions are provided. There is also a base class if you need to make your own. The implementation of ``ConditionalSum`` is very simple and looks like this:

.. code:: python

    from djconnagg.aggregates import ConditionalAggregate, SQLConditionalAggregate

    class ConditionalSum(ConditionalAggregate):
        name = 'ConditionalSum'

        class SQLClass(SQLConditionalAggregate):
            sql_function = 'SUM'
            default = 0
