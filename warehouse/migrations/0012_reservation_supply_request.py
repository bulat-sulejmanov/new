from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('warehouse', '0011_alter_stock_unique_together_alter_stock_location_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='reservation',
            name='supply_request',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='reservations',
                to='warehouse.supplyrequest',
                verbose_name='По заявке',
            ),
        ),
        migrations.AddIndex(
            model_name='reservation',
            index=models.Index(
                fields=['supply_request', 'status'],
                name='warehouse_r_supply__status_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='reservation',
            index=models.Index(
                fields=['supply_request', 'product', 'status'],
                name='warehouse_r_supply__prod_stat_idx',
            ),
        ),
    ]