from django.db import migrations


def ensure_legacy_payment_tables(apps, schema_editor):
    """Repair kept test DBs where payments.0001 is recorded but legacy tables are absent."""
    existing_tables = set(schema_editor.connection.introspection.table_names())
    for model_name in ('Promotion', 'Payment', 'Wallet', 'WalletTransaction'):
        model = apps.get_model('payments', model_name)
        if model._meta.db_table not in existing_tables:
            schema_editor.create_model(model)
            existing_tables.add(model._meta.db_table)


class Migration(migrations.Migration):

    dependencies = [
        ('payments', '0002_invoice'),
    ]

    operations = [
        migrations.RunPython(ensure_legacy_payment_tables, migrations.RunPython.noop),
    ]
