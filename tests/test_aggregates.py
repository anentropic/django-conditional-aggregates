import re
from unittest import TestCase

from django.db.models import Q
from django.db.models.sql.where import WhereNode

from djconnagg import ConditionalCount, ConditionalSum
from djconnagg.aggregates import render_q, transform_q

from testapp.models import Customer, Stat


def flatten_q_children(q, all_children):
    """
    Recursively get the children of a Q object into a flat list.

    (Q objects can have a nested structure when combined via parenthetical
    operations)
    """
    for child in q.children:
        if isinstance(child, Q):
            flatten_q_children(child, all_children)
        else:
            try:
                # Django 1.7
                child, joins_used = child
            except TypeError:
                # Django 1.6
                pass
            all_children.append(child)


def quote_char(connection):
    """
    Returns the quote char used by db backend.

    (we ask the backend to quote an empty string - we get back two quote chars
    and return one of them)
    """
    return connection.ops.quote_name('')[0]


WHITESPACE = re.compile(r'\s+|\n*', re.MULTILINE)


def normalize_whitespace(src):
    return WHITESPACE.sub(' ', src)


class AggregatesTest(TestCase):
    """
    TODO:
    for some bizarre reason these tests pass if run directly under py.test
    but not if run under tox... under tox the order of fields in the
    rendered sql is not stable. So the SQL queries are equivalent but string
    matching doesn't work. Hard to imagine why it should change behaviour!
    """

    maxDiff = None

    def test_transform_q(self):
        q = (
            (Q(detail='f') | ~Q(detail='g')) |
            Q(stat_type='u', event_type='i', detail='shu/p') & ~Q(detail='e')
        )
        query = Stat.objects.all().query
        transform_q(q, query)

        all_children = []
        flatten_q_children(q, all_children)
        for child in all_children:
            self.assertIsInstance(child, (Q, WhereNode))

    def test_render_q(self):
        q = (
            (Q(detail='f') | ~Q(detail='g')) |
            Q(stat_type='u', event_type='i', detail='shu/p') & ~Q(detail='e')
        )
        query = Stat.objects.all().query
        transform_q(q, query)

        compiler = query.get_compiler('default')

        sql, params = render_q(q, compiler.quote_name_unless_alias,
                               compiler.connection)
        self.assertEqual(
            tuple(params),
            ('f', 'g', 'u', 'shu/p', 'i', 'e')
        )
        rendered = sql % tuple(params)

        expected = unicode(
            '('
            '{0}testapp_stat{0}.{0}detail{0} = f  OR'
            ' (NOT ({0}testapp_stat{0}.{0}detail{0} = g ))'
            ' OR ('
            '({0}testapp_stat{0}.{0}stat_type{0} = u'
            '  AND {0}testapp_stat{0}.{0}detail{0} = shu/p'
            '  AND {0}testapp_stat{0}.{0}event_type{0} = i'
            '  AND (NOT ({0}testapp_stat{0}.{0}detail{0} = e )))'
            '))'
        ).format(quote_char(compiler.connection))

        self.assertEqual(
            normalize_whitespace(rendered),
            normalize_whitespace(expected)
        )

    def test_conditional_sum_as_sql(self):
        qs = Stat.objects.values('campaign_id').annotate(
            impressions=ConditionalSum(
                'count',
                when=Q(stat_type='a', event_type='v')
            )
        )
        compiler = qs.query.get_compiler('default')

        sql, params = compiler.as_sql()
        self.assertEqual(
            tuple(params),
            ('a', 'v')
        )
        rendered = sql % params

        expected = unicode(
            'SELECT {0}testapp_stat{0}.{0}campaign_id{0},'
            ' SUM(CASE WHEN'
            ' ({0}testapp_stat{0}.{0}stat_type{0} = a'
            '  AND {0}testapp_stat{0}.{0}event_type{0} = v'
            ' ) THEN {0}testapp_stat{0}.{0}count{0} ELSE 0 END'
            ') AS {0}impressions{0}'
            ' FROM {0}testapp_stat{0}'
            ' GROUP BY {0}testapp_stat{0}.{0}campaign_id{0}'
        )
        if 'mysql' in compiler.connection.__class__.__module__:
            expected += u' ORDER BY NULL'
        expected = expected.format(quote_char(compiler.connection))

        self.assertEqual(
            normalize_whitespace(rendered),
            normalize_whitespace(expected)
        )

    def test_conditional_sum_in_clause_as_sql(self):
        qs = Stat.objects.values('campaign_id').annotate(
            impressions=ConditionalSum(
                'count',
                when=Q(stat_type='a', event_type__in=('v', 'b'))
            )
        )
        compiler = qs.query.get_compiler('default')

        sql, params = compiler.as_sql()
        self.assertEqual(
            tuple(params),
            ('a', 'v', 'b')
        )
        rendered = sql % params

        expected = unicode(
            'SELECT {0}testapp_stat{0}.{0}campaign_id{0},'
            ' SUM(CASE WHEN'
            ' ({0}testapp_stat{0}.{0}stat_type{0} = a'
            '  AND {0}testapp_stat{0}.{0}event_type{0} IN (v, b)'
            ' ) THEN {0}testapp_stat{0}.{0}count{0} ELSE 0 END'
            ') AS {0}impressions{0}'
            ' FROM {0}testapp_stat{0}'
            ' GROUP BY {0}testapp_stat{0}.{0}campaign_id{0}'
        )
        if 'mysql' in compiler.connection.__class__.__module__:
            expected += u' ORDER BY NULL'
        expected = expected.format(quote_char(compiler.connection))

        self.assertEqual(
            normalize_whitespace(rendered),
            normalize_whitespace(expected)
        )

    def test_conditional_sum_across_relation_as_sql(self):
        qs = Customer.objects.values('stat__campaign_id').annotate(
            impressions=ConditionalSum(
                'stat__count',
                when=Q(stat__stat_type='a', stat__event_type='v')
            )
        )
        compiler = qs.query.get_compiler('default')

        sql, params = compiler.as_sql()
        self.assertEqual(
            tuple(params),
            ('a', 'v')
        )
        rendered = sql % params

        expected = unicode(
            'SELECT {0}testapp_stat{0}.{0}campaign_id{0},'
            ' SUM(CASE WHEN'
            ' ({0}testapp_stat{0}.{0}stat_type{0} = a'
            '  AND {0}testapp_stat{0}.{0}event_type{0} = v'
            ' ) THEN {0}testapp_stat{0}.{0}count{0} ELSE 0 END'
            ') AS {0}impressions{0}'
            ' FROM {0}testapp_customer{0}'
            '  LEFT OUTER JOIN {0}testapp_stat{0}'
            '  ON ({0}testapp_customer{0}.{0}id{0} = {0}testapp_stat{0}.{0}customer_id{0})'
            ' GROUP BY {0}testapp_stat{0}.{0}campaign_id{0}'
        )
        if 'mysql' in compiler.connection.__class__.__module__:
            expected += u' ORDER BY NULL'
        expected = expected.format(quote_char(compiler.connection))

        self.assertEqual(
            normalize_whitespace(rendered),
            normalize_whitespace(expected)
        )

    def test_conditional_sum_across_relation_local_filter_as_sql(self):
        qs = (
            Customer.objects
            .filter(name='Big Corp')
            .values('stat__campaign_id')
            .annotate(
                impressions=ConditionalSum(
                    'stat__count',
                    when=Q(stat__stat_type='a', stat__event_type='v')
                )
            )
        )
        compiler = qs.query.get_compiler('default')

        sql, params = compiler.as_sql()
        self.assertEqual(
            tuple(params),
            ('a', 'v', 'Big Corp')
        )
        rendered = sql % params

        expected = unicode(
            'SELECT {0}testapp_stat{0}.{0}campaign_id{0},'
            ' SUM(CASE WHEN'
            ' ({0}testapp_stat{0}.{0}stat_type{0} = a'
            '  AND {0}testapp_stat{0}.{0}event_type{0} = v'
            ' ) THEN {0}testapp_stat{0}.{0}count{0} ELSE 0 END'
            ') AS {0}impressions{0}'
            ' FROM {0}testapp_customer{0}'
            '  LEFT OUTER JOIN {0}testapp_stat{0}'
            '  ON ({0}testapp_customer{0}.{0}id{0} = {0}testapp_stat{0}.{0}customer_id{0})'
            ' WHERE {0}testapp_customer{0}.{0}name{0} = Big Corp'
            ' GROUP BY {0}testapp_stat{0}.{0}campaign_id{0}'
        )
        if 'mysql' in compiler.connection.__class__.__module__:
            expected += u' ORDER BY NULL'
        expected = expected.format(quote_char(compiler.connection))

        self.assertEqual(
            normalize_whitespace(rendered),
            normalize_whitespace(expected)
        )

    def test_conditional_count_as_sql(self):
        qs = Stat.objects.values('campaign_id').annotate(
            impressions=ConditionalCount(
                when=Q(stat_type='a', event_type='v')
            )
        )
        compiler = qs.query.get_compiler('default')

        sql, params = compiler.as_sql()
        self.assertEqual(
            tuple(params),
            ('a', 'v')
        )
        rendered = sql % params

        expected = unicode(
            'SELECT {0}testapp_stat{0}.{0}campaign_id{0},'
            ' COUNT(CASE WHEN'
            ' ({0}testapp_stat{0}.{0}stat_type{0} = a'
            '  AND {0}testapp_stat{0}.{0}event_type{0} = v'
            ' ) THEN 1 ELSE NULL END'
            ') AS {0}impressions{0}'
            ' FROM {0}testapp_stat{0}'
            ' GROUP BY {0}testapp_stat{0}.{0}campaign_id{0}'
        )
        if 'mysql' in compiler.connection.__class__.__module__:
            expected += u' ORDER BY NULL'
        expected = expected.format(quote_char(compiler.connection))

        self.assertEqual(
            normalize_whitespace(rendered),
            normalize_whitespace(expected)
        )

    def test_reuse_aggregate(self):
        """
        ensure we are cloning the ``when`` object internally, as it gets
        mutated during processing
        """
        when = Q(stat_type='a', event_type='v')
        Stat.objects.values('campaign_id').annotate(
            impressions=ConditionalSum('count', when=when)
        )
        try:
            Stat.objects.values('campaign_id').annotate(
                impressions=ConditionalSum('count', when=when)
            )
        except Exception as e:
            self.fail("Failed to reuse `when` Q object, raised: {}".format(e))
