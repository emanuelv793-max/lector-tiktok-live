# Lector de comentarios TikTok LIVE

Aplicación moderna para Windows que muestra y lee en voz alta los comentarios de un TikTok LIVE con voces neuronales en español.

![Logo del Lector TikTok LIVE](assets/app-icon.png)

## Descargar

Descarga la versión más reciente desde [GitHub Releases](https://github.com/emanuelv793-max/lector-tiktok-live/releases/latest) y abre `LectorTikTokLive-Moderno.exe`.

> Windows puede mostrar una advertencia de SmartScreen porque el ejecutable no tiene una firma digital comercial. Comprueba que la descarga procede de este repositorio.

## Uso

1. Abre `LectorTikTokLive-Moderno.exe`.
2. Escribe el usuario que está emitiendo (por ejemplo, `@miusuario`).
3. Pulsa **Conectar**.

No requiere iniciar sesión en TikTok. El usuario debe estar en directo y el equipo debe tener conexión a Internet.

## Controles

- **Leer nombres**: dice quién ha escrito antes de leer el comentario.
- **Voz activada**: permite silenciar o reactivar la lectura.
- **Probar voz**: reproduce una frase para comprobar la salida de audio de Windows.
- **Voz natural**: permite elegir voces neuronales de España o México. Necesita Internet; si el servicio no responde, se utiliza automáticamente la voz local de Windows.
- **Velocidad**: ajusta la rapidez de la voz de Windows.
- **Parar**: desconecta la aplicación del LIVE.

## Si la voz no se escucha en la emisión

Primero pulsa **Probar voz**. Si se oye en el ordenador pero no en el LIVE, activa
el audio del sistema/escritorio en TikTok LIVE Studio y selecciona el mismo
dispositivo de salida que utiliza Windows. El lector reproduce por la salida de
Windows; LIVE Studio debe capturar esa salida para enviarla a los espectadores.

## Nota técnica

La conexión usa [TikTokLive](https://github.com/isaackogan/TikTokLive), una API comunitaria no oficial. TikTok puede cambiar su sistema y requerir una actualización futura de la aplicación.

## Ejecutar desde el código

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

Para compilar el ejecutable:

```powershell
.\build.ps1
```
