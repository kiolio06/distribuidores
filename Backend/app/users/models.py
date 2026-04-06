from pydantic import BaseModel, EmailStr, Field
from typing import Optional

class UserBase(BaseModel):
    nombre: str
    pais: str
    correo_electronico: EmailStr
    phone: str = Field(..., min_length=7, max_length=15)

class UserCreate(UserBase):
    password: str = Field(..., min_length=8)
    rol: str = Field(
        ...,
        description="Rol del usuario: distribuidor_nacional, distribuidor_internacional, produccion, facturacion, bodega"
    )
    cdi: Optional[str] = Field(None, description="Ubicación de la bodega: medellin o guarne")
    tipo_precio: Optional[str] = Field(
        None,
        description="Solo para distribuidores: sin_iva, con_iva, sin_iva_internacional"
    )
    unidades_individuales: Optional[bool] = Field(
        False, description="Indica si el distribuidor maneja unidades individuales (solo distribuidores)"
    )
    minimo_compra: Optional[float] = Field(        # ← NUEVO
        None,
        description="Monto mínimo de compra en COP. Solo para distribuidores.",
        ge=0  # ge=0 significa "greater than or equal to 0", valida que no sea negativo
    )


# MODELO DE RESPUESTA PARA USUARIOS
class UserResponse(BaseModel):
    id: str
    nombre: str
    correo_electronico: str
    rol: str
    phone: str
    estado: str
    fecha_ultimo_acceso: str
    admin_id: str | None = None  # Puede ser opcional
    tipo_precio: str | None = None  # Solo para distribuidores
    unidades_individuales: bool | None = None  # Solo para distribuidores
    minimo_compra: float | None = None             # ← NUEVO


class AdminCreate(BaseModel):
    nombre: str
    pais: str
    whatsapp: str
    correo_electronico: EmailStr
    password: str = Field(..., min_length=8)
    rol: str = Field(..., description="Rol del admin: Admin")

class DistribuidorCreate(UserBase):
    password: str = Field(..., min_length=8)
    admin_id: str
    
class UserUpdate(BaseModel):
    nombre: Optional[str] = None
    correo_electronico: Optional[str] = None
    rol: Optional[str] = None
    phone: Optional[str] = None
    estado: Optional[str] = None
    tipo_precio: Optional[str] = None
    contrasena: Optional[str] = None
    minimo_compra: Optional[float] = Field(None, ge=0)  # ← NUEVO


