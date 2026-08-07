# Seguridad

## Versiones compatibles

Solo la versión publicada más reciente recibe correcciones de seguridad.

## Informar de una vulnerabilidad

No publiques datos sensibles ni instrucciones de explotación en un issue público. Usa el formulario privado de [GitHub Security Advisories](https://github.com/emanuelv793-max/lector-tiktok-live/security/advisories/new) e incluye una descripción, pasos para reproducir el problema y su posible impacto.

## Descargar con seguridad

Descarga el programa únicamente desde [GitHub Releases](https://github.com/emanuelv793-max/lector-tiktok-live/releases/latest). Puedes calcular su huella con:

```powershell
Get-FileHash .\LectorTikTokLive-Moderno.exe -Algorithm SHA256
```

Compara el resultado con el archivo `SHA256SUMS.txt` de la misma versión y analiza el ejecutable con Microsoft Defender antes de abrirlo.

## Privacidad y límites

- La aplicación no pide ni guarda contraseñas, cookies ni credenciales de TikTok.
- Los comentarios se reciben mediante TikTokLive, una biblioteca comunitaria no oficial.
- Al usar una voz neuronal, el texto que se va a leer se envía al servicio de voz de Microsoft. Si falla, se utiliza la voz local de Windows.
- Ningún programa puede garantizar protección absoluta frente a ataques futuros. Las dependencias y el código se revisan automáticamente, pero el ejecutable todavía no cuenta con una firma digital comercial.
