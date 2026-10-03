import uuid
from django.conf import settings
from django.db import migrations,models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies=[('productos','0012_producto_oferta_precio_actualizado'),migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations=[
        migrations.CreateModel(name='CotizacionAneleRevision',fields=[('id',models.UUIDField(default=uuid.uuid4,editable=False,primary_key=True,serialize=False)),('datos',models.JSONField()),('creado_en',models.DateTimeField(auto_now_add=True)),('aplicado_en',models.DateTimeField(blank=True,null=True)),('resultado',models.JSONField(default=dict)),('usuario',models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,to=settings.AUTH_USER_MODEL))]),
        migrations.CreateModel(name='CotizacionAneleVinculo',fields=[('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),('clave',models.CharField(max_length=64,unique=True)),('actualizado_en',models.DateTimeField(auto_now=True)),('producto',models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,to='productos.producto'))]),
    ]
