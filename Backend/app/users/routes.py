from fastapi import APIRouter, Depends, HTTPException, status
from app.core.security import pwd_context
from app.auth.routes import get_current_user
from datetime import datetime
from typing import Dict, List
from bson import ObjectId
from app.users.models import (
    AdminCreate,
    DistribuidorCreate,
    UserCreate,
    UserResponse,
    UserUpdate
)
from app.core.database import (
    collection_admin, 
    collection_distribuidores,
    collection_produccion,
    collection_facturas,
    collection_bodegas
)

router = APIRouter()

# Endpoint para crear Admin (superusuario)
@router.post("/admin/", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def crear_admin(admin: AdminCreate):
    # Verificar si el admin ya existe
    if await collection_admin.find_one({"correo_electronico": admin.correo_electronico}):
        raise HTTPException(
            status_code=400,
            detail="El admin ya está registrado"
        )
    
    hashed_password = pwd_context.hash(admin.password)
    
    nuevo_admin = {
        "nombre": admin.nombre,
        "pais": admin.pais,
        "whatsapp": admin.whatsapp,
        "correo_electronico": admin.correo_electronico,
        "hashed_password": hashed_password,
        "rol": admin.rol,
        "fecha_creacion": datetime.now()
    }
    
    result = await collection_admin.insert_one(nuevo_admin)
    
    return UserResponse(
        id=str(result.inserted_id),
        nombre=admin.nombre,
        pais=admin.pais,
        correo_electronico=admin.correo_electronico,
        phone=admin.whatsapp,
        rol=admin.rol,
        estado="Activo",
        fecha_ultimo_acceso=datetime.now().strftime("%Y-%m-%d %H:%M"),
        admin_id="system"
    )

# # Endpoint para crear Distribuidores (solo por Admin)
# @router.post("/distribuidores/", response_model=UserResponse)
# async def crear_distribuidor(
#     distribuidor: DistribuidorCreate,
#     current_user: dict = Depends(get_current_user)
# ):
#     if current_user["rol"] != "Admin":
#         raise HTTPException(
#             status_code=status.HTTP_403_FORBIDDEN,
#             detail="Solo los Admin pueden crear distribuidores"
#         )
    
#     # Verificar admin_id válido
#     if not ObjectId.is_valid(distribuidor.admin_id):
#         raise HTTPException(status_code=400, detail="ID de admin inválido")
    
#     # Verificar correo único
#     if await collection_distribuidores.find_one({"correo_electronico": distribuidor.correo_electronico}):
#         raise HTTPException(
#             status_code=400,
#             detail="El correo ya está registrado"
#         )
    
#     hashed_password = pwd_context.hash(distribuidor.password)
    
#     nuevo_distribuidor = {
#         "nombre": distribuidor.nombre,
#         "pais": distribuidor.pais,
#         "correo_electronico": distribuidor.correo_electronico,
#         "phone": distribuidor.phone,
#         "hashed_password": hashed_password,
#         "rol": "distribuidor",
#         "tipo_precio": "con_iva",  # Valor por defecto
#         "admin_id": ObjectId(distribuidor.admin_id),
#         "fecha_creacion": datetime.now(),
#         "estado": "Activo"
#     }
    
#     result = await collection_distribuidores.insert_one(nuevo_distribuidor)
    
#     return UserResponse(
#         id=str(result.inserted_id),
#         nombre=distribuidor.nombre,
#         pais=distribuidor.pais,
#         correo_electronico=distribuidor.correo_electronico,
#         phone=distribuidor.phone,
#         rol="distribuidor",
#         estado="Activo",
#         fecha_ultimo_acceso=datetime.now().strftime("%Y-%m-%d %H:%M"),
#         admin_id=distribuidor.admin_id,
#         tipo_precio="con_iva"
#     )

# ENDPOINT PARA CREAR USUARIOS CON DIFERENTES ROLES
@router.post("/create-users/", response_model=UserResponse)
async def crear_usuario(
    usuario: UserCreate,
    current_user: Dict = Depends(get_current_user)
):
    # --- Verificar permisos de admin o bodega ---
    if current_user["rol"] not in ["Admin", "bodega"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo los Admin o Bodega pueden crear usuarios"
        )

    # --- Obtener admin o bodega creador ---
    creador = await (collection_admin.find_one({"correo_electronico": current_user["email"]})
                     if current_user["rol"] == "Admin"
                     else collection_bodegas.find_one({"correo_electronico": current_user["email"]}))
    if not creador:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{current_user['rol']} no encontrado"
        )

    # --- Normalizar datos ---
    correo_normalizado = usuario.correo_electronico.lower()
    rol_normalizado = usuario.rol.lower()

    # --- Verificar correo único ---
    for collection in [collection_distribuidores, collection_produccion, collection_facturas, collection_bodegas]:
        if await collection.find_one({"correo_electronico": correo_normalizado}):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El correo ya está registrado"
            )

    # --- Roles válidos ---
    roles_validos = [
        "distribuidor_nacional",
        "distribuidor_internacional",
        "produccion",
        "facturacion",
        "bodega"
    ]
    if rol_normalizado not in roles_validos:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Rol no válido. Debe ser uno de: {', '.join(roles_validos)}"
        )

    # --- Validación específica para distribuidores ---
    unidades_individuales = None
    if rol_normalizado in ["distribuidor_nacional", "distribuidor_internacional"]:
        if not usuario.tipo_precio:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Los distribuidores deben tener un tipo de precio"
            )
        if usuario.tipo_precio not in ["sin_iva", "con_iva", "sin_iva_internacional"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Tipo de precio no válido. Opciones: sin_iva, con_iva, sin_iva_internacional"
            )

        unidades_individuales = usuario.unidades_individuales if usuario.unidades_individuales is not None else False

        if usuario.cdi and usuario.cdi.lower() not in ["medellin", "guarne"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="CDI no válido para distribuidor. Opciones: medellin, guarne"
            )

    # --- Validación específica para bodega ---
    if rol_normalizado == "bodega":
        if not usuario.cdi:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Las bodegas deben especificar el campo 'cdi' (medellin o guarne)"
            )
        if usuario.cdi.lower() not in ["medellin", "guarne"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Valor de 'cdi' no válido. Opciones: medellin, guarne"
            )

    # --- Generar ID único ---
    async def generar_id_unico():
        max_ids = []
        for collection in [collection_distribuidores, collection_produccion, collection_facturas, collection_bodegas]:
            last_user = await collection.find_one(sort=[("id", -1)])
            if last_user and "id" in last_user:
                try:
                    max_ids.append(int(last_user["id"][1:]))
                except (ValueError, IndexError):
                    continue
        nuevo_num = max(max_ids) + 1 if max_ids else 1
        return f"U{nuevo_num:03d}"

    try:
        nuevo_id = await generar_id_unico()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error generando ID único: {str(e)}"
        )

    # --- Crear documento de usuario ---
    nuevo_usuario = {
        "id": nuevo_id,
        "nombre": usuario.nombre,
        "pais": usuario.pais,
        "correo_electronico": correo_normalizado,
        "phone": usuario.phone,
        "hashed_password": pwd_context.hash(usuario.password),
        "rol": rol_normalizado,
        "estado": "Activo",
        "fecha_ultimo_acceso": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "admin_id": creador["_id"],
    }

    if rol_normalizado in ["distribuidor_nacional", "distribuidor_internacional"]:
        nuevo_usuario["tipo_precio"] = usuario.tipo_precio
        nuevo_usuario["unidades_individuales"] = unidades_individuales
        if usuario.cdi:
            nuevo_usuario["cdi"] = usuario.cdi.lower()
        
        if usuario.minimo_compra is not None:
            nuevo_usuario["minimo_compra"] = usuario.minimo_compra

    if rol_normalizado == "bodega":
        nuevo_usuario["cdi"] = usuario.cdi.lower()

    # --- Determinar colección destino ---
    target_collection = {
        "distribuidor_nacional": collection_distribuidores,
        "distribuidor_internacional": collection_distribuidores,
        "produccion": collection_produccion,
        "facturacion": collection_facturas,
        "bodega": collection_bodegas
    }[rol_normalizado]

    # --- Insertar usuario ---
    result = await target_collection.insert_one(nuevo_usuario)

    if not result.inserted_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al crear usuario"
        )

    return UserResponse(
        id=nuevo_id,
        nombre=usuario.nombre,
        correo_electronico=correo_normalizado,
        rol=rol_normalizado,
        estado="Activo",
        fecha_ultimo_acceso=nuevo_usuario["fecha_ultimo_acceso"],
        admin_id=str(creador["_id"]),
        phone=usuario.phone,
        tipo_precio=usuario.tipo_precio if rol_normalizado in ["distribuidor_nacional", "distribuidor_internacional"] else None,
        minimo_compra=usuario.minimo_compra
    )


# ENDPOINT PARA OBTENER LOS USUARIOS
@router.get("/usuarios/", response_model=List[UserResponse])
async def obtener_usuarios(
    current_user: Dict = Depends(get_current_user)
):
    print("📢 Iniciando obtención de usuarios")  # Debug

    rol = current_user["rol"]
    email = current_user["email"]

    # --- ADMIN: ve todos los usuarios ---
    if rol == "Admin":
        print("🔑 Rol Admin: viendo todos los usuarios")  # Debug

        collections = {
            "distribuidor": collection_distribuidores,
            "produccion": collection_produccion,
            "facturacion": collection_facturas
        }

        usuarios = []
        seen_ids = set()

        for rol_col, collection in collections.items():
            print(f"🔍 Buscando usuarios en la colección: {rol_col}")
            async for user in collection.find():
                if user["id"] not in seen_ids:
                    seen_ids.add(user["id"])
                    usuarios.append(user)

    # --- BODEGA: ve solo usuarios con su mismo CDI ---
    elif rol == "bodega":
        print(f"🔑 Rol Bodega ({email}): filtrando usuarios por CDI")  # Debug

        bodega = await collection_bodegas.find_one({"correo_electronico": email})
        if not bodega:
            raise HTTPException(status_code=404, detail="Bodega no encontrada")

        cdi = bodega.get("cdi")
        if cdi not in ["medellin", "guarne"]:
            raise HTTPException(status_code=400, detail="CDI de bodega no válido")

        print(f"🏢 Bodega CDI: {cdi}")  # Debug

        collections = {
            "distribuidor": collection_distribuidores,
            "produccion": collection_produccion,
            "facturacion": collection_facturas
        }

        usuarios = []
        seen_ids = set()

        for rol_col, collection in collections.items():
            print(f"🔍 Buscando usuarios en la colección: {rol_col} con CDI={cdi}")
            async for user in collection.find({"cdi": cdi}):
                if user["id"] not in seen_ids:
                    seen_ids.add(user["id"])
                    usuarios.append(user)

    else:
        print(f"❌ Acceso denegado para rol: {rol}")  # Debug
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No autorizado para ver usuarios"
        )

    print(f"📢 Total de usuarios encontrados: {len(usuarios)}")  # Debug

    # --- Formatear respuesta ---
    response = [
        UserResponse(
            id=u["id"],
            nombre=u["nombre"],
            correo_electronico=u["correo_electronico"],
            phone=u["phone"],
            rol=u["rol"],
            estado=u["estado"],
            fecha_ultimo_acceso=u["fecha_ultimo_acceso"],
            tipo_precio=u.get("tipo_precio"),
            admin_id=str(u["admin_id"])
        ) for u in usuarios
    ]

    print(f"📢 Respuesta preparada: {len(response)} usuarios")  # Debug
    return response

# ENDPOINT PARA ACTUALIZAR USUARIOS 
@router.put("/update-user/{usuario_id}", response_model=UserResponse)
async def editar_usuario(
    usuario_id: str,
    usuario_actualizado: UserUpdate,
    current_user: Dict = Depends(get_current_user)
):
    print(f"📢 Iniciando edición de usuario: {usuario_id}")

    # 1. Verificar permisos de admin
    if current_user["rol"] != "Admin":
        print("❌ Acceso denegado: Solo los Admin pueden editar usuarios")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo los Admin pueden editar usuarios"
        )

    # 2. Mapeo de roles a colecciones
    ROLES_COLECCIONES = {
        "distribuidor": collection_distribuidores,
        "produccion": collection_produccion,
        "facturacion": collection_facturas
    }

    # 3. Buscar usuario en todas las colecciones
    usuario_original = None
    coleccion_actual = None
    rol_actual = None
    
    for rol, coleccion in ROLES_COLECCIONES.items():
        usuario_original = await coleccion.find_one({"id": usuario_id})
        if usuario_original:
            coleccion_actual = coleccion
            rol_actual = rol
            break

    if not usuario_original:
        print("❌ Usuario no encontrado")
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    print(f"📢 Usuario original encontrado: {usuario_original}")

    # 4. Preparar datos para actualización
    update_data = usuario_actualizado.dict(exclude_unset=True)
    nuevo_rol = update_data.get("rol", rol_actual)

    # 5. Manejo de contraseña si está en la actualización
    if "contrasena" in update_data:
        hashed_password = pwd_context.hash(update_data["contrasena"])
        update_data["hashed_password"] = hashed_password
        del update_data["contrasena"]
        print("🔑 Contraseña actualizada (hash generado)")

    # 6. Validaciones para tipo_precio
    if "tipo_precio" in update_data:
        if rol_actual != "distribuidor" and nuevo_rol != "distribuidor":
            raise HTTPException(
                status_code=400,
                detail="El campo tipo_precio solo aplica para distribuidores"
            )
        
        tipos_precio_validos = ["sin_iva", "con_iva", "sin_iva_internacional"]
        if update_data["tipo_precio"] not in tipos_precio_validos:
            raise HTTPException(
                status_code=400,
                detail=f"Tipo de precio no válido. Opciones: {tipos_precio_validos}"
            )

    # 7. Manejar tipo_precio para no distribuidores
    if nuevo_rol != "distribuidor" and "tipo_precio" in update_data:
        print("⚠️ Advertencia: tipo_precio solo aplica para distribuidores")
        update_data.pop("tipo_precio")

    print(f"📢 Datos para actualización: {update_data}")

    # 8. Verificar si hay cambio de rol
    if nuevo_rol != rol_actual:
        print(f"📢 Cambio de rol detectado: {rol_actual} -> {nuevo_rol}")

        if nuevo_rol not in ROLES_COLECCIONES:
            print(f"❌ Rol '{nuevo_rol}' no válido")
            raise HTTPException(
                status_code=400,
                detail=f"Rol '{nuevo_rol}' no válido. Roles permitidos: {list(ROLES_COLECCIONES.keys())}"
            )

        coleccion_destino = ROLES_COLECCIONES[nuevo_rol]
        nuevo_documento = {**usuario_original, **update_data}
        
        if nuevo_rol != "distribuidor":
            nuevo_documento.pop("tipo_precio", None)
        
        print(f"📢 Nuevo documento para colección destino: {nuevo_documento}")

        try:
            await coleccion_actual.delete_one({"id": usuario_id})
            print(f"📢 Usuario eliminado de la colección actual: {rol_actual}")
            
            await coleccion_destino.insert_one(nuevo_documento)
            print(f"📢 Usuario insertado en la nueva colección: {nuevo_rol}")
            
            usuario_actualizado_db = await coleccion_destino.find_one({"id": usuario_id})
        except Exception as e:
            print(f"❌ Error al cambiar de colección: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Error al cambiar de colección: {str(e)}"
            )
    else:
        print("📢 Actualización sin cambio de rol")

        for campo in ["_id", "id", "admin_id"]:
            update_data.pop(campo, None)

        await coleccion_actual.update_one(
            {"id": usuario_id},
            {"$set": update_data}
        )
        usuario_actualizado_db = await coleccion_actual.find_one({"id": usuario_id})

    # 9. Preparar respuesta
    if usuario_actualizado_db:
        if isinstance(usuario_actualizado_db.get("_id"), ObjectId):
            usuario_actualizado_db["_id"] = str(usuario_actualizado_db["_id"])
        if isinstance(usuario_actualizado_db.get("admin_id"), ObjectId):
            usuario_actualizado_db["admin_id"] = str(usuario_actualizado_db["admin_id"])

        # Eliminar campos sensibles de la respuesta
        usuario_actualizado_db.pop("hashed_password", None)
        usuario_actualizado_db.pop("contrasena", None)

    print(f"📢 Usuario actualizado: {usuario_actualizado_db}")

    return UserResponse(**usuario_actualizado_db)

# Endpoint para desactivar un usuario
@router.put("/deactivate-user/{usuario_id}/cambiar-estado", response_model=UserResponse)
async def cambiar_estado_usuario(
    usuario_id: str,
    current_user: Dict = Depends(get_current_user)
):
    # Verificar permisos
    if current_user["rol"] != "Admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo los Admin pueden cambiar estados de usuarios"
        )

    # Buscar el usuario
    usuario_encontrado = None
    coleccion_encontrada = None
    colecciones = [collection_distribuidores, collection_produccion, collection_facturas]

    for coleccion in colecciones:
        usuario_encontrado = await coleccion.find_one({"id": usuario_id})
        if usuario_encontrado:
            coleccion_encontrada = coleccion
            break

    if not usuario_encontrado:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    # Cambiar estado
    nuevo_estado = "Inactivo" if usuario_encontrado.get("estado") == "Activo" else "Activo"
    await coleccion_encontrada.update_one(
        {"id": usuario_id},
        {"$set": {"estado": nuevo_estado}}
    )

    # Obtener datos actualizados
    usuario_actualizado = await coleccion_encontrada.find_one({"id": usuario_id})
    
    # Convertir ObjectIds
    if usuario_actualizado:
        usuario_actualizado = {
            **usuario_actualizado,
            "_id": str(usuario_actualizado["_id"]),
            "admin_id": str(usuario_actualizado.get("admin_id")) if usuario_actualizado.get("admin_id") else None
        }

    return UserResponse(**usuario_actualizado)

# Endpoint para obtener información del usuario autenticado
@router.get("/auth/me", response_model=dict)
async def read_user_me(current_user: dict = Depends(get_current_user)):
    """
    Get information of the authenticated user from distribuidores collection.
    """
    try:
        # Check if user is a distribuidor
        if current_user["rol"] != "distribuidor":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This endpoint is only for distribuidores"
            )
        
        # Find user in distribuidores collection
        user = await collection_distribuidores.find_one(
            {"correo_electronico": current_user["email"]},
            {"hashed_password": 0}  # Exclude password from response
        )
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found in distribuidores collection"
            )
            
        # Convert ObjectId to string
        user["_id"] = str(user["_id"])
        user["admin_id"] = str(user["admin_id"])
        
        return user
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

@router.patch("/distribuidores/{distribuidor_id}/unidades-individuales")
async def toggle_unidades_individuales(
    distribuidor_id: str,
    current_user: Dict = Depends(get_current_user)
):
    """
    Endpoint para alternar el permiso de unidades individuales de un distribuidor
    Requiere rol Admin o Bodega
    """
    try:
        # Verificar permisos
        if current_user["rol"] not in ["Admin", "bodega"]:
            raise HTTPException(status_code=403, detail="Acceso denegado")

        # Buscar el distribuidor por el campo 'id' (no _id)
        distribuidor = await collection_distribuidores.find_one({"id": distribuidor_id})
        if not distribuidor:
            raise HTTPException(status_code=404, detail="Distribuidor no encontrado")

        # Alternar el valor actual
        nuevo_valor = not distribuidor.get("unidades_individuales", False)
        
        # Actualizar en la base de datos usando el campo 'id'
        result = await collection_distribuidores.update_one(
            {"id": distribuidor_id},
            {"$set": {"unidades_individuales": nuevo_valor}}
        )

        if result.modified_count == 1:
            return {
                "message": "Permiso actualizado correctamente",
                "distribuidor_id": distribuidor_id,
                "unidades_individuales": nuevo_valor
            }
        else:
            raise HTTPException(status_code=400, detail="No se pudo actualizar el distribuidor")

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error al actualizar unidades individuales: {str(e)}")
        raise HTTPException(status_code=500, detail="Error interno del servidor")

