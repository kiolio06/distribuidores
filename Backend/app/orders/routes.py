from app.auth.routes import get_current_user
from fastapi import APIRouter, HTTPException, Depends, Body, status
from bson import ObjectId
from datetime import datetime, timedelta
import os
import smtplib
import ssl
from email.message import EmailMessage
from app.core.database import (
    collection_pedidos,
    collection_productos,
    collection_distribuidores,
    collection_admin,
    collection_bodegas,
    collection_ordenes
)

router = APIRouter()

EMAIL_SENDER = os.getenv("EMAIL_REMITENTE")
EMAIL_PASSWORD = os.getenv("EMAIL_CONTRASENA")  # Contraseña de aplicación generada en Gmail
print("EMAIL_SENDER:", EMAIL_SENDER)  # Debe imprimir info@rizosfelices.co
print("EMAIL_PASSWORD:", EMAIL_PASSWORD)
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 465  # Puerto seguro con SSL

def enviar_correo(destinatario, asunto, mensaje):
    msg = EmailMessage()
    msg["Subject"] = asunto
    msg["From"] = EMAIL_SENDER
    msg["To"] = destinatario
    msg.set_content(mensaje, subtype="html")  # Enviar contenido en HTML

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, context=context) as server:
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.send_message(msg)
    print(f"📧 Correo enviado a {destinatario}")

@router.post("/create-purchase-order/")
async def crear_orden_compra(orden: dict, current_user: dict = Depends(get_current_user)):
    print("📢 Iniciando creación de ORDEN DE COMPRA")

    # Verificar si el usuario tiene el rol de distribuidor
    if current_user.get("rol") not in ["distribuidor", "distribuidor_nacional", "distribuidor_internacional"]:
        print(f"❌ Acceso denegado: Rol no permitido: {current_user.get('rol')}")
        raise HTTPException(status_code=403, detail="Solo los distribuidores pueden crear órdenes de compra")

    # Obtener distribuidor actual
    distribuidor = await collection_distribuidores.find_one({"correo_electronico": current_user["email"]})
    if not distribuidor:
        print("❌ Distribuidor no encontrado")
        raise HTTPException(status_code=404, detail="Distribuidor no encontrado")

    distribuidor_id = str(distribuidor["_id"])
    distribuidor_nombre = distribuidor.get("nombre", "Desconocido")
    distribuidor_phone = distribuidor.get("phone", "No registrado")
    tipo_precio = distribuidor.get("tipo_precio", "con_iva")

    print(f"📢 Distribuidor encontrado: {distribuidor_nombre}, Tipo de precio: {tipo_precio}")

    # Validaciones básicas de la orden
    if "productos" not in orden or not isinstance(orden["productos"], list):
        print("❌ Orden inválida: Falta lista de productos")
        raise HTTPException(status_code=400, detail="La orden de compra debe contener una lista de productos")

    if "direccion" not in orden:
        print("❌ Orden inválida: Falta dirección")
        raise HTTPException(status_code=400, detail="La orden de compra debe incluir una dirección")

    productos_actualizados = []
    subtotal = 0
    iva_total = 0

    # Procesar cada producto de la orden
    for producto in orden["productos"]:
        if "id" not in producto or "cantidad" not in producto or "precio" not in producto:
            print(f"❌ Producto inválido: {producto}")
            raise HTTPException(status_code=400, detail="Cada producto debe tener 'id', 'cantidad' y 'precio'")

        producto_id = producto["id"]
        cantidad_solicitada = int(producto["cantidad"])
        precio_sin_iva = float(producto["precio"])  # 💡 Precio enviado desde el frontend sin IVA

        print(f"🔍 Verificando producto {producto_id}")

        producto_db = await collection_productos.find_one({"id": producto_id})
        if not producto_db:
            raise HTTPException(status_code=404, detail=f"Producto con ID {producto_id} no encontrado")

        # # Obtener el stock actual y convertirlo a int
        # stock_actual = producto_db.get("stock", 0)
        # if isinstance(stock_actual, dict):
        #     # Si en tu esquema usas un dict por bodegas y aquí no segmentas por bodega, toma cualquier valor (o ajusta según tu lógica)
        #     stock_actual = int(list(stock_actual.values())[0])
        # else:
        #     stock_actual = int(stock_actual)

        # if cantidad_solicitada > stock_actual:
        #     raise HTTPException(status_code=400, detail=f"Stock insuficiente para producto {producto_id}")

        # Calcular precio con o sin IVA
        if tipo_precio == "con_iva":
            iva = round(precio_sin_iva * 0.19, 2)
            precio_con_iva = round(precio_sin_iva + iva, 2)
            iva_producto = round(iva * cantidad_solicitada, 2)
        elif tipo_precio in ["sin_iva", "sin_iva_internacional"]:
            precio_con_iva = precio_sin_iva
            iva_producto = 0
            iva = 0
        else:
            raise HTTPException(status_code=400, detail="Tipo de precio no válido")

        print(f"✅ Producto {producto_id}: Sin IVA: {precio_sin_iva}, IVA unit: {iva}, Con IVA: {precio_con_iva}")


        productos_actualizados.append({
            "id": producto_id,
            "nombre": producto_db["nombre"],
            "cantidad": cantidad_solicitada,
            "precio": precio_con_iva,
            "precio_sin_iva": precio_sin_iva,
            "iva_unitario": iva,
            "total": precio_con_iva * cantidad_solicitada,
            "tipo_precio": tipo_precio
        })

        subtotal += precio_sin_iva * cantidad_solicitada
        iva_total += iva_producto


    total_orden = subtotal + iva_total
    print(f"📦 Subtotal: {subtotal}, IVA Total: {iva_total}, Total Orden: {total_orden}")

    # ── Validar mínimo de compra ──────────────────────────────────────────────
    minimo_compra = distribuidor.get("minimo_compra")
    if minimo_compra is not None and total_orden < minimo_compra:
        raise HTTPException(
            status_code=400,
            detail=f"El monto mínimo de compra es ${minimo_compra:,.0f} COP. "
                    f"Tu orden es de ${total_orden:,.0f} COP."
        )

    # Crear ORDEN DE COMPRA en la base de datos
    orden_compra_id = f"OC-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    nueva_orden = {
        "id": orden_compra_id,
        "distribuidor_id": distribuidor_id,
        "distribuidor_nombre": distribuidor_nombre,
        "distribuidor_phone": distribuidor_phone,
        "productos": productos_actualizados,
        "direccion": orden["direccion"],
        "notas": orden.get("notas", ""),
        "fecha": datetime.now(),
        "estado": "Orden de compra creada",
        "subtotal": subtotal,
        "iva": iva_total,
        "total": total_orden,
        "tipo_precio": tipo_precio
    }

    result = await collection_ordenes.insert_one(nueva_orden)
    print(f"📦 Orden de compra creada con ID: {orden_compra_id} y guardada en 'purchase_orders'")

    # Preparar mensajes de correo
    fecha_orden = datetime.now().strftime("%d/%m/%Y %H:%M")

    # Plantilla CSS para los correos
    estilo_correo = """
    <style>
        body { font-family: 'Arial', sans-serif; line-height: 1.6; color: #333; }
        .container { max-width: 600px; margin: 0 auto; padding: 20px; }
        .header { background-color: #f8f1e9; padding: 20px; text-align: center; border-radius: 5px 5px 0 0; }
        .logo { max-width: 150px; }
        .content { padding: 20px; background-color: #fff; border: 1px solid #e0e0e0; border-top: none; }
        .footer { text-align: center; padding: 20px; font-size: 12px; color: #777; }
        .product-table { width: 100%; border-collapse: collapse; margin: 15px 0; }
        .product-table th { background-color: #f8f1e9; text-align: left; padding: 10px; }
        .product-table td { padding: 10px; border-bottom: 1px solid #e0e0e0; }
        .totals { margin-top: 20px; padding: 15px; background-color: #f9f9f9; border-radius: 5px; }
        .totals-row { display: flex; justify-content: space-between; margin-bottom: 8px; }
        .total-final { font-weight: bold; font-size: 1.1em; border-top: 1px solid #ddd; padding-top: 10px; }
        .status { display: inline-block; padding: 5px 10px; background-color: #e3f2fd; color: #1976d2; border-radius: 3px; }
    </style>
    """

    # Tabla de productos (HTML)
    productos_html = """
    <table class="product-table">
        <thead>
            <tr>
                <th>Producto</th>
                <th>Cantidad</th>
                <th>Precio Unitario</th>
                <th>Total</th>
            </tr>
        </thead>
        <tbody>
    """
    for p in productos_actualizados:
        productos_html += f"""
        <tr>
            <td>{p['nombre']} (ID: {p['id']})</td>
            <td>{p['cantidad']}</td>
            <td>${p['precio']:,.0f}</td>
            <td>${p['total']:,.0f}</td>
        </tr>
        """
        if tipo_precio == "con_iva":
            productos_html += f"""
            <tr style="color: #666; font-size: 0.9em;">
                <td colspan="4">
                    (IVA incluido: ${p['iva_unitario']:,.0f} x {p['cantidad']} = ${p['iva_unitario'] * p['cantidad']:,.0f})
                </td>
            </tr>
            """
    productos_html += """
        </tbody>
    </table>
    """

    # Sección de totales
    totales_html = f"""
    <div class="totals">
        <div class="totals-row">
            <span>Subtotal:</span>
            <span>${subtotal:,.0f}</span>
        </div>
        {f'<div class="totals-row"><span>IVA (19%):</span><span>${iva_total:,.0f}</span></div>' if tipo_precio == "con_iva" else ""}
        <div class="totals-row total-final">
            <span>Total de la Orden:</span>
            <span>${total_orden:,.0f}</span>
        </div>
    </div>
    """

    # 📧 Correos (admin/tesorería y CDI)
    mensaje_admin = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Nueva Orden de Compra {orden_compra_id}</title>
        {estilo_correo}
    </head>
    <body>
        <div class="container">
            <div class="header">
                <img src="https://rizosfelicesdata.s3.us-east-2.amazonaws.com/logo+principal+rosado+letra+blanco_Mesa+de+tra+(1).png" alt="Rizos Felices" class="logo">
                <h1>Nueva Orden de Compra Recibida</h1>
            </div>
            <div class="content">
                <h2>Detalles de la Orden</h2>
                <p><strong>Número de Orden:</strong> {orden_compra_id}</p>
                <p><strong>Fecha y Hora:</strong> {fecha_orden}</p>
                <p><strong>Estado:</strong> <span class="status">Orden de compra creada</span></p>
                <h3>Información del Distribuidor</h3>
                <p><strong>Nombre:</strong> {distribuidor_nombre}</p>
                <p><strong>Teléfono:</strong> {distribuidor_phone}</p>
                <h3>Detalles de Entrega</h3>
                <p><strong>Dirección:</strong> {orden['direccion']}</p>
                <p><strong>Notas:</strong> {orden.get('notas', 'Ninguna')}</p>
                <h3>Productos Solicitados</h3>
                {productos_html}
                {totales_html}
            </div>
            <div class="footer">
                <p>© {datetime.now().year} Rizos Felices. Todos los derechos reservados.</p>
                <p>Este es un correo automático, por favor no responder.</p>
            </div>
        </div>
    </body>
    </html>
    """

    mensaje_distribuidor = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Confirmación de Orden de Compra {orden_compra_id}</title>
        {estilo_correo}
    </head>
    <body>
        <div class="container">
            <div class="header">
                <img src="https://rizosfelicesdata.s3.us-east-2.amazonaws.com/logo+principal+rosado+letra+blanco_Mesa+de+tra+(1).png" alt="Rizos Felices" class="logo">
                <h1>¡Gracias por tu orden de compra!</h1>
            </div>
            <div class="content">
                <p>Hemos recibido tu orden correctamente y está siendo procesada. A continuación encontrarás los detalles:</p>
                <h2>Resumen de la Orden</h2>
                <p><strong>Número de Orden:</strong> {orden_compra_id}</p>
                <p><strong>Fecha y Hora:</strong> {fecha_orden}</p>
                <p><strong>Estado:</strong> <span class="status">Orden de compra creada</span></p>
                <h3>Detalles de Entrega</h3>
                <p><strong>Dirección:</strong> {orden['direccion']}</p>
                <p><strong>Notas:</strong> {orden.get('notas', 'Ninguna')}</p>
                <h3>Productos</h3>
                {productos_html}
                {totales_html}
                <p style="margin-top: 20px;">
                    <strong>Nota:</strong> Te notificaremos cuando tu orden esté en camino.
                    Para cualquier consulta, puedes responder a este correo o contactarnos al teléfono de soporte.
                </p>
            </div>
            <div class="footer">
                <p>© {datetime.now().year} Rizos Felices. Todos los derechos reservados.</p>
                <p>Este es un correo automático, por favor no responder.</p>
            </div>
        </div>
    </body>
    </html>
    """

    # Enviar a Tesorería
    enviar_correo(
        "tesoreria@rizosfelices.co",
        f"📦 Nueva Orden de Compra: {orden_compra_id} - {distribuidor_nombre}",
        mensaje_admin
    )

    # Enviar adicional al CDI según distribuidor
    correos_cdi = {
        "medellin": "cdimedellin@rizosfelices.co",
        "guarne": "produccion@rizosfelices.co"
    }
    cdi_distribuidor = distribuidor.get("cdi", "").lower()
    correo_cdi = correos_cdi.get(cdi_distribuidor)
    if correo_cdi:
        enviar_correo(
            correo_cdi,
            f"📦 Nueva Orden de Compra (CDI {cdi_distribuidor.capitalize()}): {orden_compra_id} - {distribuidor_nombre}",
            mensaje_admin
        )
        print(f"📧 Correo adicional enviado a {correo_cdi}")

    # Correo al distribuidor
    enviar_correo(
        current_user["email"],
        f"✅ Confirmación de Orden de Compra: {orden_compra_id}",
        mensaje_distribuidor
    )

    print(f"📧 Correos enviados para la orden {orden_compra_id}")

    # Convertir ObjectId a string para la respuesta JSON
    nueva_orden["_id"] = str(result.inserted_id)

    return {
        "message": "Orden de compra creada exitosamente",
        "orden_compra": nueva_orden
    }

# ENDPOINT PARA OBTENER LOS PEDIDOS
@router.get("/get-all-orders/")
async def obtener_pedidos(current_user: dict = Depends(get_current_user)):
    try:
        email = current_user["email"]
        rol = current_user["rol"]
        filtro_pedidos = {}

        # Lógica para distribuidores (solo ven sus propios pedidos)
        if rol.startswith("distribuidor"):
            distribuidor = await collection_distribuidores.find_one({"correo_electronico": email})
            if not distribuidor:
                raise HTTPException(status_code=404, detail="Distribuidor no encontrado")
            
            distribuidor_id = str(distribuidor["_id"])
            filtro_pedidos = {"distribuidor_id": distribuidor_id}
        
        # Para admin, facturacion y produccion no aplicamos filtros (ven todos)
        elif rol in ["Admin", "facturacion", "produccion"]:
            pass  # No se aplica filtro
        
        # Lógica específica para bodegas
        elif rol == "bodega":
            bodega = await collection_bodegas.find_one({"correo_electronico": email})
            if not bodega:
                raise HTTPException(status_code=404, detail="Bodega no encontrada")
            
            cdi = bodega.get("cdi")
            if not cdi:
                raise HTTPException(status_code=400, detail="La bodega no tiene un CDI asignado")
            
            if cdi == "guarne":
                filtro_pedidos = {"tipo_precio": "sin_iva_internacional"}
            elif cdi == "medellin":
                filtro_pedidos = {"tipo_precio": {"$in": ["con_iva", "sin_iva"]}}
            else:
                raise HTTPException(status_code=400, detail="CDI de bodega no válido")

        # Obtener pedidos según filtro
        pedidos = await collection_pedidos.find(filtro_pedidos).to_list(None)
        
        # Obtener todos los distribuidores relevantes en una sola consulta
        distribuidor_ids = list({pedido["distribuidor_id"] for pedido in pedidos})
        distribuidores = await collection_distribuidores.find(
            {"_id": {"$in": [ObjectId(id) for id in distribuidor_ids]}}
        ).to_list(None)
        
        # Crear mapa rápido de distribuidores
        distribuidor_map = {str(distribuidor["_id"]): {
            "nombre": distribuidor.get("nombre", "Desconocido"),
            "telefono": distribuidor.get("telefono", ""),
            "email": distribuidor.get("correo_electronico", "")
        } for distribuidor in distribuidores}
        
        # Formatear respuesta
        pedidos_formateados = []
        for pedido in pedidos:
            info_distribuidor = distribuidor_map.get(pedido["distribuidor_id"], {
                "nombre": "Desconocido",
                "telefono": "",
                "email": ""
            })
            
            # Adaptar precios para bodega Guarne (mostrar siempre sin IVA)
            if rol == "bodega" and bodega.get("cdi") == "guarne":
                for producto in pedido.get("productos", []):
                    producto["precio"] = producto.get("precio_sin_iva", producto["precio"])
                    producto["iva_unitario"] = 0
            
            pedido_formateado = {
                "id": pedido.get("id", str(pedido["_id"])),
                "_id": str(pedido["_id"]),
                "fecha": pedido.get("fecha", datetime.now()).isoformat(),
                "productos": pedido.get("productos", []),
                "estado": pedido.get("estado", "pendiente"),
                "tipo_precio": pedido.get("tipo_precio"),
                "distribuidor_nombre": info_distribuidor["nombre"],
                "distribuidor_telefono": info_distribuidor["telefono"],
                "distribuidor_email": info_distribuidor["email"],
                "distribuidor_id": pedido["distribuidor_id"],
                "total": sum(p["precio"] * p["cantidad"] for p in pedido.get("productos", [])),
                "total_iva": sum(p.get("iva_unitario", 0) * p["cantidad"] for p in pedido.get("productos", []))
            }
            pedidos_formateados.append(pedido_formateado)
        
        # Ordenar por fecha descendente
        pedidos_formateados.sort(key=lambda x: x["fecha"], reverse=True)
        
        return {"pedidos": pedidos_formateados}
    
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error al obtener pedidos: {str(e)}")
        raise HTTPException(status_code=500, detail="Error interno al obtener pedidos")

# Endpoint para obtener detalles de un pedido específico
@router.get("/ordenes/{pedido_id}")
async def obtener_detalles_pedido(pedido_id: str, current_user: dict = Depends(get_current_user)):
    try:
        email = current_user["email"]
        rol = current_user["rol"]

        print(f"🔎 [DETALLE PEDIDO] Usuario autenticado: {email}, Rol: {rol}")

        # Buscar el pedido SOLAMENTE por su ID personalizado (no usar _id)
        pedido = await collection_pedidos.find_one({"id": pedido_id})
        if not pedido:
            print(f"❌ Pedido con id {pedido_id} no encontrado")
            raise HTTPException(status_code=404, detail="Pedido no encontrado")

        # Convertir ObjectId a str para la respuesta JSON
        pedido["_id"] = str(pedido["_id"])
        print(f"📦 Pedido encontrado: {pedido.get('id')}")

        # --- ADMIN ---
        if rol == "Admin":
            admin = await collection_admin.find_one({"correo_electronico": email})
            if not admin:
                print("❌ Admin no encontrado")
                raise HTTPException(status_code=404, detail="Admin no encontrado")
            print("✅ Admin autorizado - Acceso completo a todos los pedidos")
            # Eliminada la validación de admin_id para permitir acceso completo

        # --- DISTRIBUIDOR (nacional e internacional) ---
        elif rol.startswith("distribuidor_"):
            distribuidor = await collection_distribuidores.find_one({"correo_electronico": email})
            if not distribuidor:
                print("❌ Distribuidor no encontrado")
                raise HTTPException(status_code=404, detail="Distribuidor no encontrado")

            if str(pedido["distribuidor_id"]) != str(distribuidor["_id"]):
                print("⛔ Pedido no pertenece a este distribuidor")
                raise HTTPException(status_code=403, detail="No tienes permisos para ver este pedido")

        # --- PRODUCCION / FACTURACION ---
        elif rol in ["produccion", "facturacion"]:
            pass  # Acceso permitido sin restricciones

        # --- BODEGA (Medellín y Guarne) ---
        elif rol == "bodega":
            bodega = await collection_bodegas.find_one({"correo_electronico": email})
            if not bodega:
                print("❌ Bodega no encontrada")
                raise HTTPException(status_code=404, detail="Bodega no encontrada")

            cdi = bodega.get("cdi")
            if not cdi:
                print("❌ Bodega sin CDI asignado")
                raise HTTPException(status_code=400, detail="La bodega no tiene un CDI asignado")

            print(f"🏭 Bodega {cdi} accediendo al pedido - Sin restricciones de tipo_precio")

        else:
            print(f"⛔ Rol no autorizado: {rol}")
            raise HTTPException(status_code=403, detail="Rol no autorizado para ver pedidos")

        # Obtener información del distribuidor para la respuesta
        distribuidor = await collection_distribuidores.find_one({"_id": ObjectId(pedido["distribuidor_id"])})
        pedido["distribuidor_nombre"] = distribuidor.get("nombre") if distribuidor else "Desconocido"
        pedido["distribuidor_telefono"] = distribuidor.get("telefono") if distribuidor else ""

        # Calcular totales
        pedido["total"] = sum(p["precio"] * p["cantidad"] for p in pedido.get("productos", []))
        pedido["total_iva"] = sum(p.get("iva_unitario", 0) * p["cantidad"] for p in pedido.get("productos", []))

        print("✅ Devolviendo detalles del pedido")
        return {"pedido": pedido}

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error crítico: {str(e)}")
        raise HTTPException(status_code=500, detail="Error interno al obtener detalles del pedido")

# ENDPOINT PARA CAMBIAR ESTADO DE PEDIDO (facturado/en camino)
@router.put("/ordenes/{pedido_id}/estado")
async def cambiar_estado_orden(
    pedido_id: str,
    nuevo_estado: str = Body(..., embed=True),
    current_user: dict = Depends(get_current_user)
):
    try:
        email = current_user["email"]
        rol = current_user["rol"]

        # Verificar permisos
        if rol not in ["Admin", "produccion", "facturacion", "distribuidor", "bodega"]:
            raise HTTPException(status_code=403, detail="No tienes permisos para cambiar estados")

        # Validar estado
        if nuevo_estado not in ["facturado", "en camino"]:
            raise HTTPException(status_code=400, detail="Estado no válido")

        # Buscar y actualizar usando el ID personalizado (no ObjectId)
        resultado = await collection_pedidos.update_one(
            {"id": pedido_id},  # Buscar por tu ID personalizado
            {"$set": {"estado": nuevo_estado}}
        )

        if resultado.modified_count == 0:
            raise HTTPException(status_code=404, detail="Pedido no encontrado")

        # Obtener pedido actualizado
        pedido_actualizado = await collection_pedidos.find_one({"id": pedido_id})
        
        # Limpiar el _id de MongoDB si existe
        if pedido_actualizado and "_id" in pedido_actualizado:
            del pedido_actualizado["_id"]

        return {
            "mensaje": f"Estado actualizado a '{nuevo_estado}'",
            "pedido": pedido_actualizado
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Endpoint de Estadísticas Generales
@router.get("/estadisticas/generales")
async def obtener_estadisticas_generales(current_user: dict = Depends(get_current_user)):
    """
    Devuelve estadísticas generales.
    Solo 'bodega' ve datos filtrados por su CDI (medellin o guarne).
    """
    try:
        email = current_user["email"]
        rol = current_user["rol"]
        filtro_pedidos = {}
        cdi = None

        print(f"📊 Usuario autenticado: {email}, Rol: {rol}")

        # --- FILTROS SOLO PARA BODEGA ---
        if rol == "bodega":
            bodega = await collection_bodegas.find_one({"correo_electronico": email})
            if not bodega:
                raise HTTPException(status_code=404, detail="Bodega no encontrada")
            cdi = bodega.get("cdi", None)

            if cdi == "medellin":
                filtro_pedidos = {"tipo_precio": {"$in": ["sin_iva", "con_iva"]}}
            elif cdi == "guarne":
                filtro_pedidos = {"tipo_precio": "sin_iva_internacional"}
            else:
                raise HTTPException(status_code=400, detail="CDI de bodega no válido")

        elif rol not in ["Admin", "produccion", "facturacion", "distribuidor"]:
            raise HTTPException(status_code=403, detail="Rol no autorizado para ver estadísticas")

        # --- 1. Pedidos totales ---
        total_pedidos = await collection_pedidos.count_documents(filtro_pedidos)

        # --- 2. Productos activos ---
        try:
            total_productos = await collection_productos.count_documents({
                "activo": True,
                "eliminado": {"$ne": True}
            })
        except Exception as e:
            print(f"❌ Error al contar productos: {str(e)}")
            total_productos = 0

        # --- 3. Distribuidores ---
        total_distribuidores = await collection_distribuidores.count_documents({})

        # --- 4. Ventas mensuales ---
        fecha_inicio_mes = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        fecha_fin_mes = (fecha_inicio_mes + timedelta(days=32)).replace(day=1)

        pipeline_ventas = [
            {
                "$match": {
                    "fecha": {"$gte": fecha_inicio_mes, "$lt": fecha_fin_mes},
                    "estado": "facturado",
                    **filtro_pedidos
                }
            },
            {"$unwind": "$productos"},
            {
                "$group": {
                    "_id": None,
                    "total_ventas": {
                        "$sum": {"$multiply": ["$productos.cantidad", "$productos.precio"]}
                    },
                    "count_ventas": {"$sum": 1}
                }
            }
        ]

        ventas_mensuales = await collection_pedidos.aggregate(pipeline_ventas).to_list(length=1)
        total_ventas = ventas_mensuales[0]["total_ventas"] if ventas_mensuales and "total_ventas" in ventas_mensuales[0] else 0

        return {
            "pedidos_totales": total_pedidos,
            "total_productos": total_productos,
            "total_distribuidores": total_distribuidores,
            "ventas_mensuales": total_ventas,
            "cdi": cdi,
            "fecha_consulta": datetime.now().isoformat()
        }

    except Exception as e:
        print(f"❌ Error al obtener estadísticas: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error al obtener estadísticas: {str(e)}"
        )

## Endpoint de Pedidos Recientes
@router.get("/api/pedidos/recientes")
async def obtener_pedidos_recientes(current_user: dict = Depends(get_current_user)):
    """
    Devuelve los 5 pedidos más recientes.
    Solo el rol bodega ve pedidos filtrados por CDI y tipo_precio.
    """
    try:
        email = current_user["email"]
        rol = current_user["rol"]

        print(f"📢 Usuario autenticado: {email}, Rol: {rol}")

        filtro_pedidos = {}

        # --- FILTROS SOLO PARA BODEGA ---
        if rol == "bodega":
            bodega = await collection_bodegas.find_one({"correo_electronico": email})
            if not bodega:
                raise HTTPException(status_code=404, detail="Bodega no encontrada")

            cdi = bodega.get("cdi", None)
            print(f"🏢 Bodega CDI: {cdi}")

            if cdi == "medellin":
                filtro_pedidos = {"tipo_precio": {"$in": ["sin_iva", "con_iva"]}}
            elif cdi == "guarne":
                filtro_pedidos = {"tipo_precio": "sin_iva_internacional"}
            else:
                raise HTTPException(status_code=400, detail="CDI de bodega no válido")

        # --- OTROS ROLES ---
        elif rol not in ["Admin", "distribuidor", "produccion", "facturacion"]:
            raise HTTPException(status_code=403, detail="Rol no autorizado para ver pedidos recientes")

        # --- OBTENER PEDIDOS RECIENTES ---
        pedidos = await collection_pedidos.find(filtro_pedidos) \
            .sort("fecha", -1) \
            .limit(5) \
            .to_list(length=None)

        # --- FORMATEAR RESPUESTA ---
        for pedido in pedidos:
            pedido["id"] = str(pedido["_id"])
            pedido["total"] = sum(p["cantidad"] * p["precio"] for p in pedido["productos"])
            del pedido["_id"]

        return pedidos

    except Exception as e:
        print(f"❌ Error al obtener pedidos recientes: {e}")
        raise HTTPException(status_code=500, detail="Error al obtener pedidos recientes")

@router.get("/productos/populares")
async def obtener_productos_populares(current_user: dict = Depends(get_current_user)):
    """
    Devuelve los 5 productos más vendidos en el mes actual.
    Solo 'bodega' ve datos filtrados por CDI y tipo_precio.
    """
    try:
        email = current_user["email"]
        rol = current_user["rol"].lower()
        print(f"🔍 Consulta de productos populares por {email} (Rol: {rol})")

        # --- Validación de roles ---
        if rol == "facturacion":
            print("⛔ Acceso denegado a facturación")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permisos para ver esta información"
            )

        # --- Fechas para el mes actual ---
        hoy = datetime.now()
        fecha_inicio_mes = hoy.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        fecha_fin_mes = (fecha_inicio_mes + timedelta(days=32)).replace(day=1)
        print(f"📅 Rango del mes: {fecha_inicio_mes} a {fecha_fin_mes}")

        # --- Filtro base para pedidos facturados ---
        filtro_match = {
            "fecha": {"$gte": fecha_inicio_mes, "$lt": fecha_fin_mes},
            "estado": "facturado",
            "productos": {"$exists": True, "$not": {"$size": 0}}
        }

        # --- Filtro adicional para BODEGA ---
        if rol == "bodega":
            bodega = await collection_bodegas.find_one({"correo_electronico": email})
            if not bodega:
                raise HTTPException(status_code=404, detail="Bodega no encontrada")

            cdi = bodega.get("cdi")
            print(f"🏢 Bodega CDI: {cdi}")

            if cdi == "medellin":
                filtro_match["tipo_precio"] = {"$in": ["sin_iva", "con_iva"]}
            elif cdi == "guarne":
                filtro_match["tipo_precio"] = "sin_iva_internacional"
            else:
                raise HTTPException(status_code=400, detail="CDI de bodega no válido")

        # --- Pipeline de agregación ---
        pipeline = [
            {"$match": filtro_match},
            {"$unwind": "$productos"},
            {"$match": {"productos.id": {"$exists": True}, "productos.cantidad": {"$gt": 0}}},
            {
                "$group": {
                    "_id": "$productos.id",
                    "nombre": {"$first": "$productos.nombre"},
                    "categoria": {"$first": "$productos.categoria"},
                    "precio": {"$avg": "$productos.precio"},
                    "vendidos": {"$sum": "$productos.cantidad"},
                    "num_pedidos": {"$sum": 1}
                }
            },
            {"$sort": {"vendidos": -1}},
            {"$limit": 5},
            {
                "$lookup": {
                    "from": "productos",
                    "localField": "_id",
                    "foreignField": "id",
                    "as": "producto_info"
                }
            },
            {"$unwind": "$producto_info"},
            {
                "$addFields": {
                    "stock": "$producto_info.stock",
                    "activo": "$producto_info.activo",
                    "imagen": "$producto_info.imagen",
                    "en_produccion": "$producto_info.en_produccion"
                }
            },
            {
                "$project": {
                    "_id": 0,
                    "id": "$_id",
                    "nombre": 1,
                    "categoria": 1,
                    "precio": 1,
                    "vendidos": 1,
                    "stock": 1,
                    "activo": 1,
                    "imagen": 1,
                    "num_pedidos": 1,
                    "en_produccion": 1
                }
            }
        ]

        print("🔎 Ejecutando pipeline de agregación...")
        productos = await collection_pedidos.aggregate(pipeline).to_list(length=None)
        print(f"✅ Productos encontrados: {len(productos)}")

        # --- Filtrado adicional para producción ---
        if rol == "produccion":
            productos = [p for p in productos if p.get("en_produccion", False)]
            print(f"🛠️ Filtrados para producción: {len(productos)}")

        return productos

    except Exception as e:
        print(f"❌ Error en agregación: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error al obtener productos populares: {str(e)}"
        )

@router.get("/mis-ordenes")  # Si el prefijo es "/orders/pedidos"
async def obtener_mis_pedidos(current_user: dict = Depends(get_current_user)):
    print("🚀 Entrando en obtener_mis_pedidos")
    try:
        print(f"📢 Usuario autenticado: {current_user}")

        if not current_user["rol"].startswith("distribuidor"):
            print("❌ No es distribuidor")
            raise HTTPException(status_code=403, detail="Solo los distribuidores pueden acceder a sus pedidos.")

        distribuidor = await collection_distribuidores.find_one({"correo_electronico": current_user["email"]})
        print(f"🔍 Distribuidor encontrado: {distribuidor}")

        if not distribuidor:
            raise HTTPException(status_code=404, detail="Distribuidor no encontrado.")

        distribuidor_id = str(distribuidor["_id"])
        print(f"📦 Buscando pedidos con distribuidor_id: {distribuidor_id}")

        pedidos = await collection_pedidos.find({"distribuidor_id": distribuidor_id}).to_list(500)
        print(f"📜 Pedidos encontrados: {len(pedidos)}")

        for pedido in pedidos:
            pedido["_id"] = str(pedido["_id"])
            if "fecha" in pedido and hasattr(pedido["fecha"], "isoformat"):
                pedido["fecha"] = pedido["fecha"].isoformat()

        return {"pedidos": pedidos}

    except Exception as e:
        print(f"❌ Error al obtener pedidos: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error al obtener pedidos: {str(e)}")
        
@router.get("/detalles-pedidos/{pedido_id}")
async def obtener_detalles_pedido(
    pedido_id: str, 
    current_user: dict = Depends(get_current_user)
):
    try:
        print(f"🔍 Buscando pedido con ID: {pedido_id}")
        
        # 1. BUSCAR EL PEDIDO (por id personalizado o _id)
        pedido = await collection_pedidos.find_one({"id": pedido_id})
        
        if not pedido:
            try:
                pedido = await collection_pedidos.find_one({"_id": ObjectId(pedido_id)})
            except:
                pass
        
        if not pedido:
            raise HTTPException(status_code=404, detail="Pedido no encontrado")

        # Convertir ObjectId a string
        pedido["_id"] = str(pedido.get("_id"))
        print(f"📦 Pedido encontrado: {pedido.get('id')}")

        # 2. VALIDACIÓN DE PERMISOS POR ROL
        rol = current_user["rol"]
        email = current_user["email"]

        # ADMINISTRADOR
        if rol == "Admin":
            admin = await collection_admin.find_one({"correo_electronico": email})
            if not admin:
                raise HTTPException(status_code=404, detail="Admin no encontrado")

            distribuidor = await collection_distribuidores.find_one({"_id": ObjectId(pedido.get("distribuidor_id"))})
            if not distribuidor or str(distribuidor.get("admin_id")) != str(admin["_id"]):
                raise HTTPException(status_code=403, detail="No autorizado para este pedido")

        # DISTRIBUIDOR (nacional e internacional)
        elif rol.startswith("distribuidor_"):
            distribuidor = await collection_distribuidores.find_one({"correo_electronico": email})
            if not distribuidor:
                raise HTTPException(status_code=404, detail="Distribuidor no encontrado")
            
            if str(pedido.get("distribuidor_id")) != str(distribuidor["_id"]):
                raise HTTPException(status_code=403, detail="Solo puedes ver tus propios pedidos")

        # BODEGA
        elif rol == "bodega":
            bodega = await collection_bodegas.find_one({"correo_electronico": email})
            if not bodega:
                raise HTTPException(status_code=404, detail="Bodega no encontrada")
            
            cdi = bodega.get("cdi")
            tipo_precio = pedido.get("tipo_precio")
            
            if cdi == "medellin" and tipo_precio not in ["sin_iva", "con_iva"]:
                raise HTTPException(status_code=403, detail="No autorizado para este tipo de pedido")
            elif cdi == "guarne" and tipo_precio != "sin_iva_internacional":
                raise HTTPException(status_code=403, detail="No autorizado para este tipo de pedido")

        # PRODUCCIÓN O FACTURACIÓN
        elif rol not in ["produccion", "facturacion"]:
            raise HTTPException(status_code=403, detail="Rol no autorizado")

        # 3. FORMATEAR RESPUESTA
        productos = pedido.get("productos", [])
        distribuidor_info = await obtener_info_distribuidor(pedido.get("distribuidor_id"))

        response = {
            "id": pedido.get("id"),
            "fecha": pedido.get("fecha", datetime.now().isoformat()),
            "estado": pedido.get("estado", "pendiente"),
            "productos": productos,
            "total": sum(p.get("precio", 0) * p.get("cantidad", 0) for p in productos),
            "distribuidor_id": pedido.get("distribuidor_id"),
            "distribuidor_nombre": pedido.get("distribuidor_nombre"),
            "distribuidor_phone": pedido.get("distribuidor_phone"),
            "direccion": pedido.get("direccion"),  # ✅ Añadir esta línea
            "notas": pedido.get("notas"),
            "subtotal": pedido.get("subtotal", 0),
            "iva": pedido.get("iva", 0),
            "total": pedido.get("total", 0),
            "tipo_precio": pedido.get("tipo_precio"),
            "bodega_procesadora": pedido.get("bodega_procesadora"),
            "fecha_procesado": pedido.get("fecha_procesado"),
            "procesado_por": pedido.get("procesado_por"),
            "notas_procesamiento": pedido.get("notas_procesamiento"),
            "notas_orden_original": pedido.get("notas_orden_original"),
            "distribuidor_info": distribuidor_info  # Información adicional del distribuidor
        }

        return {"pedido": response}

    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"❌ Error crítico: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error interno: {str(e)}")

async def obtener_info_distribuidor(distribuidor_id: str):
    if not distribuidor_id:
        return None
    
    distribuidor = await collection_distribuidores.find_one({"_id": ObjectId(distribuidor_id)})
    if not distribuidor:
        return None
    
    return {
        "nombre": distribuidor.get("nombre"),
        "email": distribuidor.get("correo_electronico"),
        "pais": distribuidor.get("pais")
    }

