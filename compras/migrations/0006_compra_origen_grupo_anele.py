from django.db import migrations, models
class Migration(migrations.Migration):
    dependencies = [('compras', '0005_compra_modo_factura_sin_producto')]
    operations = [migrations.AddField(model_name='compra',name='origen_anele_id',field=models.UUIDField(null=True,blank=True,unique=True,editable=False)),migrations.AddField(model_name='compra',name='origen_anele_datos',field=models.JSONField(default=dict,blank=True,editable=False))]
