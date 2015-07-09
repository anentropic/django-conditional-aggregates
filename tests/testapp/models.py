from django.db import models


class Customer(models.Model):
    name = models.CharField(max_length=16)


class Stat(models.Model):
    """
    Just imagine you need some kind of advertising stats...
    """

    TYPE_CHOICES = (
        ('a', 'Aggregate'),
        ('u', 'Unique'),
    )
    customer = models.ForeignKey(Customer)
    stat_type = models.CharField(max_length=1, choices=TYPE_CHOICES)
    event_type = models.CharField(max_length=2, db_index=True)
    detail = models.CharField(max_length=100, db_index=True)
    campaign_id = models.IntegerField(null=True, blank=True, db_index=True)
    count = models.IntegerField(default=0)

    def __unicode__(self):
        return (
            "Stat:"
            " customer={customer_id},"
            " stat_type={stat_type},"
            " event_type={event_type},"
            " detail={detail},"
            " campaign_id={campaign_id},"
            " count={count}"
        ).format(**self.__dict__)
