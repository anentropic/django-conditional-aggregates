import django
from django.db.models import Aggregate, Q
from django.db.models.sql.aggregates import Aggregate as SQLAggregate


DJANGO_MAJOR, DJANGO_MINOR, _, _, _ = django.VERSION


def transform_q(q, query):
    """
    Replaces (lookup, value) children of Q with equivalent WhereNode objects.

    This is a pre-prep of our Q object, ready for later rendering into SQL.
    Modifies in place, no need to return.

    (We could do this in render_q, but then we'd have to pass the Query object
    from ConditionalAggregate down into SQLConditionalAggregate, which Django
    avoids to do in their API so we try and follow their lead here)
    """
    for i, child in enumerate(q.children):
        if isinstance(child, Q):
            transform_q(child, query)
        else:
            # child is (lookup, value) tuple
            where_node = query.build_filter(child)
            q.children[i] = where_node


def render_q(q, qn, connection):
    """
    Renders the Q object into SQL for the WHEN clause.

    Uses as much as possible the Django ORM machinery for SQL generation,
    handling table aliases, field quoting, parameter escaping etc.

    :param q: Q object representing the filter condition
    :param qn: db specific 'quote names' function that was passed into
        SQLAggregate.as_sql method by Django
    :param connection: Django db connection object that was passed into
        SQLAggregate.as_sql method by Django

    :returns:  (SQL template str, params list) tuple
    """
    joinstr = u' {} '.format(q.connector)
    conditions = []
    params = []

    if DJANGO_MAJOR == 1 and DJANGO_MINOR == 7:
        # in Django 1.7 WhereNode.as_sql expects `qn` to have a `compile`
        # method (i.e not really expecting a quote names function any more
        # they are expecting a django.db.models.sql.compiler.SQLCompiler)
        try:
            qn = qn.__self__
        except AttributeError:
            pass

    for child in q.children:
        if isinstance(child, Q):
            # recurse
            condition, child_params = render_q(child, qn, connection)
            conditions.append(u'({})'.format(condition))
            params.extend(child_params)
        else:
            try:
                # Django 1.7
                child, joins_used = child
            except TypeError:
                # Django 1.6
                pass
            # we expect child to be a WhereNode (see transform_q)
            condition, child_params = child.as_sql(qn, connection)
            params.extend(child_params)
            conditions.append(condition)
    rendered = u'({})'.format(joinstr.join(conditions))
    if q.negated:
        rendered = u'NOT {}'.format(rendered)
    return rendered, params


class SQLConditionalAggregate(SQLAggregate):
    """
    An aggregate like Count, Sum, but whose content is a CASE conditional

    Like Django Count() and Sum() it can be used in annotate() and aggregate()
    """
    is_ordinal = False
    is_computed = False
    sql_template = (
        '%(function)s('
        'CASE WHEN %(when_clause)s THEN %(value)s ELSE %(default)s END'
        ')'
    )

    def __init__(self, col, when, source=None,
                 is_summary=False, **extra):
        self.when = when
        super(SQLConditionalAggregate, self).__init__(col, source=source,
                                                      **extra)

    def get_value(self, **kwargs):
        return kwargs['field_name']

    def as_sql(self, qn, connection):
        params = []

        if hasattr(self.col, 'as_sql'):
            field_name, params = self.col.as_sql(qn, connection)
        elif isinstance(self.col, (list, tuple)):
            field_name = '.'.join([qn(c) for c in self.col])
        else:
            field_name = self.col

        when_clause, when_params = render_q(
            q=self.when,
            qn=qn,
            connection=connection,
        )
        params.extend(when_params)

        get_val_kwargs = locals()
        get_val_kwargs.pop('self')
        substitutions = {
            'function': self.sql_function,
            'when_clause': when_clause,
            'value': self.get_value(**get_val_kwargs),
            'default': self.default,
        }
        substitutions.update(self.extra)

        return self.sql_template % substitutions, params


class ConditionalAggregate(Aggregate):
    """
    Base class for concrete aggregate types

    e.g.
    ConditionalSum('count', when=Q(stat_type='a', event_type='v'))

    First argument is field lookup path, then we expect `when` kwarg
    to be a Django Q object representing the filter condition.
    """
    def __init__(self, lookup, when, **extra):
        self.when = when
        super(ConditionalAggregate, self).__init__(lookup, **extra)

    def add_to_query(self, query, alias, col, source, is_summary):
        # transform simple lookups to WhereNodes:
        when = self.when.clone()
        transform_q(when, query)

        aggregate = self.SQLClass(
            col=col,
            when=when,
            source=source,
            is_summary=is_summary,
            **self.extra
        )
        query.aggregates[alias] = aggregate


class ConditionalSum(ConditionalAggregate):
    """
    Works like Sum() except only sums rows that match the Q filter.

    :param lookup: (as arg) Django __ lookup path to field to sum on
    :param when: (as kwarg) a Q object specifying filter condition

    Usage:

    report = (
        Stat.objects
            .extra(select={'month': "date_format(time_period, '%%Y-%%m')"})
            .values('campaign_id', 'month')  # values + annotate = GROUP BY
            .annotate(
                impressions=ConditionalSum(
                    'count',
                    when=Q(stat_type='a', event_type='v')
                ),
                clicks=ConditionalSum(
                    'count',
                    when=Q(stat_type='a', event_type='c') & ~Q(detail='e')
                )
            )
    )
    """
    name = 'ConditionalSum'

    class SQLClass(SQLConditionalAggregate):
        sql_function = 'SUM'
        default = 0


class ConditionalCount(ConditionalAggregate):
    """
    Works like Count() except only counts rows that match the Q filter.

    :param when: (as kwarg) a Q object specifying filter condition

    Usage:

    report = (
        Stat.objects
            .extra(select={'month': "date_format(time_period, '%%Y-%%m')"})
            .values('campaign_id', 'month')  # values + annotate = GROUP BY
            .annotate(
                impressions=ConditionalCount(
                    when=Q(stat_type='a', event_type='v')
                )
            )
    )
    """
    name = 'ConditionalCount'

    def __init__(self, when, **extra):
        self.when = when
        # NOTE: passing 'id' as the lookup is a bit hacky but Django is
        # rigidly expecting a field name here, even though not needed
        super(ConditionalAggregate, self).__init__('id', **extra)

    class SQLClass(SQLConditionalAggregate):
        sql_template = (
            '%(function)s('
            'CASE WHEN %(when_clause)s THEN %(value)s ELSE %(default)s END'
            ')'
        )
        sql_function = 'COUNT'
        is_ordinal = True
        default = 'NULL'

        def get_value(self, **kwargs):
            return '1'
