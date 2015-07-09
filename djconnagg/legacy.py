from django.core.exceptions import FieldError
from django.db import connections, DEFAULT_DB_ALIAS
try:
    from django.db.models.constants import LOOKUP_SEP
except ImportError:
    from django.db.models.sql.constants import LOOKUP_SEP
from django.db.models.expressions import ExpressionNode
from django.db.models.fields import FieldDoesNotExist
from django.db.models.sql.datastructures import MultiJoin
from django.db.models.sql.expressions import SQLEvaluator
from django.db.models.sql.where import Constraint, AND


def build_filter(query, filter_expr, branch_negated=False, current_negated=False,
                 can_reuse=None):
    """
    COPIED FROM DJANGO 1.6.11 and hacked to work
    (this method doesn't exist in older Djangos... it's sort of part of a
    bigger spaghetti method, but we need at least some of what it does)

    Builds a WhereNode for a single filter clause, but doesn't add it
    to this Query. Query.add_q() will then add this filter to the where
    or having Node.
    The 'branch_negated' tells us if the current branch contains any
    negations. This will be used to determine if subqueries are needed.
    The 'current_negated' is used to determine if the current filter is
    negated or not and this will be used to determine if IS NULL filtering
    is needed.
    The difference between current_netageted and branch_negated is that
    branch_negated is set on first negation, but current_negated is
    flipped for each negation.
    Note that add_filter will not do any negating itquery, that is done
    upper in the code by add_q().
    The 'can_reuse' is a set of reusable joins for multijoins.
    The method will create a filter clause that can be added to the current
    query. However, if the filter isn't added to the query then the caller
    is responsible for unreffing the joins used.
    """
    arg, value = filter_expr
    parts = arg.split(LOOKUP_SEP)
    if not parts:
        raise FieldError("Cannot parse keyword query %r" % arg)

    # Work out the lookup type and remove it from the end of 'parts',
    # if necessary.
    lookup_type = 'exact'  # Default lookup type
    num_parts = len(parts)
    if (len(parts) > 1 and parts[-1] in query.query_terms
            and arg not in query.aggregates):
        # Traverse the lookup query to distinguish related fields from
        # lookup types.
        lookup_model = query.model
        for counter, field_name in enumerate(parts):
            try:
                lookup_field = lookup_model._meta.get_field(field_name)
            except FieldDoesNotExist:
                # Not a field. Bail out.
                lookup_type = parts.pop()
                break
            # Unless we're at the end of the list of lookups, let's attempt
            # to continue traversing relations.
            if (counter + 1) < num_parts:
                try:
                    lookup_model = lookup_field.rel.to
                except AttributeError:
                    # Not a related field. Bail out.
                    lookup_type = parts.pop()
                    break

    clause = query.where_class()
    # Interpret '__exact=None' as the sql 'is NULL'; otherwise, reject all
    # uses of None as a query value.
    if value is None:
        if lookup_type != 'exact':
            raise ValueError("Cannot use None as a query value")
        lookup_type = 'isnull'
        value = True
    elif callable(value):
        value = value()
    elif isinstance(value, ExpressionNode):
        # If value is a query expression, evaluate it
        value = SQLEvaluator(value, query, reuse=can_reuse)
    # For Oracle '' is equivalent to null. The check needs to be done
    # at this stage because join promotion can't be done at compiler
    # stage. Using DEFAULT_DB_ALIAS isn't nice, but it is the best we
    # can do here. Similar thing is done in is_nullable(), too.
    if (connections[DEFAULT_DB_ALIAS].features.interprets_empty_strings_as_nulls and
            lookup_type == 'exact' and value == ''):
        value = True
        lookup_type = 'isnull'

    for alias, aggregate in query.aggregates.items():
        if alias in (parts[0], LOOKUP_SEP.join(parts)):
            clause.add((aggregate, lookup_type, value), AND)
            return clause

    opts = query.get_meta()
    alias = query.get_initial_alias()
    allow_many = not branch_negated

    try:
        field, sources, opts, join_list, path, _ = query.setup_joins(
            parts, opts, alias, can_reuse, allow_many,
            allow_explicit_fk=True)
        if can_reuse is not None:
            can_reuse.update(join_list)
        # split_exclude() needs to know which joins were generated for the
        # lookup parts
        query._lookup_joins = join_list
    except MultiJoin as e:
        return query.split_exclude(filter_expr, LOOKUP_SEP.join(parts[:e.level]),
                                   can_reuse, e.names_with_path)

    if (lookup_type == 'isnull' and value is True and not current_negated and
            len(join_list) > 1):
        # If the comparison is against NULL, we may need to use some left
        # outer joins when creating the join chain. This is only done when
        # needed, as it's less efficient at the database level.
        query.promote_joins(join_list)

    # Process the join list to see if we can remove any inner joins from
    # the far end (fewer tables in a query is better). Note that join
    # promotion must happen before join trimming to have the join type
    # information available when reusing joins.
    col, alias, join_list = query.trim_joins(sources, join_list, path, False)
    targets = sources

    if hasattr(field, 'get_lookup_constraint'):
        constraint = field.get_lookup_constraint(query.where_class, alias, targets, sources,
                                                 lookup_type, value)
    else:
        constraint = (Constraint(alias, col, field), lookup_type, value)
    clause.add(constraint, AND)
    if current_negated and (lookup_type != 'isnull' or value is False):
        query.promote_joins(join_list)
        if (lookup_type != 'isnull' and (
                query.is_nullable(targets[0]) or
                query.alias_map[join_list[-1]].join_type == query.LOUTER)):
            # The condition added here will be SQL like this:
            # NOT (col IS NOT NULL), where the first NOT is added in
            # upper layers of code. The reason for addition is that if col
            # is null, then col != someval will result in SQL "unknown"
            # which isn't the same as in Python. The Python None handling
            # is wanted, and it can be gotten by
            # (col IS NULL OR col != someval)
            #   <=>
            # NOT (col IS NOT NULL AND col = someval).
            clause.add((Constraint(alias, col, None), 'isnull', False), AND)
    return clause
