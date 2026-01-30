# ==================== SERVIDOR DE NOTIFICACIONES PARA PRODUCCIÓN ====================
# notifications_app.py

from flask import Flask, request, jsonify
from flask_cors import CORS
import firebase_admin
from firebase_admin import credentials, messaging, firestore
import os
import json
from datetime import datetime

app = Flask(__name__)
CORS(app)

# ==================== INICIALIZAR FIREBASE ADMIN ====================
def initialize_firebase():
    try:
        # En producción, las credenciales vienen de variables de entorno
        firebase_credentials = os.environ.get('FIREBASE_CREDENTIALS')
        
        if firebase_credentials:
            # Parsear las credenciales desde la variable de entorno
            cred_dict = json.loads(firebase_credentials)
            cred = credentials.Certificate(cred_dict)
        else:
            # En desarrollo local, usar el archivo JSON
            cred = credentials.Certificate('serviceAccountKey.json')
        
        firebase_admin.initialize_app(cred)
        print('✅ Firebase Admin inicializado correctamente')
        
    except Exception as e:
        print(f'❌ Error al inicializar Firebase: {str(e)}')
        raise

initialize_firebase()
db = firestore.client()

# ==================== RUTA PRINCIPAL ====================
@app.route('/')
def index():
    return jsonify({
        'message': '🔔 Servidor de Notificaciones Push - Trans Doramald',
        'status': 'running',
        'version': '1.0.0',
        'timestamp': datetime.now().isoformat(),
        'endpoints': {
            'POST /api/notifications/send-to-user': 'Enviar notificación a un usuario',
            'POST /api/notifications/send-to-all': 'Enviar notificación a todos',
            'GET /api/notifications/users': 'Listar usuarios con tokens',
            'GET /health': 'Health check',
        }
    })

# ==================== HEALTH CHECK ====================
@app.route('/health')
def health():
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat()
    })

# ==================== ENVIAR A UN USUARIO ESPECÍFICO ====================
@app.route('/api/notifications/send-to-user', methods=['POST'])
def send_to_user():
    try:
        data = request.get_json()
        
        # Validar datos
        if not data.get('userId') or not data.get('title') or not data.get('body'):
            return jsonify({
                'error': 'Faltan datos requeridos',
                'required': ['userId', 'title', 'body']
            }), 400
        
        user_id = data['userId']
        title = data['title']
        body = data['body']
        notification_data = data.get('data', {})
        channel_id = data.get('channelId', 'general_channel')
        
        print(f'📤 Enviando notificación a usuario: {user_id}')
        
        # Obtener el token FCM del usuario
        user_ref = db.collection('usuarios_registrados').document(user_id)
        user_doc = user_ref.get()
        
        if not user_doc.exists:
            return jsonify({'error': 'Usuario no encontrado', 'userId': user_id}), 404
        
        user_data = user_doc.to_dict()
        fcm_token = user_data.get('fcmToken')
        
        if not fcm_token:
            return jsonify({'error': 'El usuario no tiene un token FCM', 'userId': user_id}), 400
        
        # Construir y enviar el mensaje
        message = messaging.Message(
            notification=messaging.Notification(title=title, body=body),
            data={**notification_data, 'channelId': channel_id},
            token=fcm_token,
            android=messaging.AndroidConfig(
                priority='high',
                notification=messaging.AndroidNotification(
                    sound='default',
                    channel_id=channel_id,
                ),
            ),
            apns=messaging.APNSConfig(
                payload=messaging.APNSPayload(
                    aps=messaging.Aps(sound='default', badge=1),
                ),
            ),
        )
        
        response = messaging.send(message)
        print(f'✅ Notificación enviada a {user_data.get("email", user_id)}')
        
        return jsonify({
            'success': True,
            'message': 'Notificación enviada exitosamente',
            'messageId': response,
            'userId': user_id,
            'email': user_data.get('email')
        })
        
    except Exception as e:
        print(f'❌ Error: {str(e)}')
        return jsonify({'error': 'Error al enviar notificación', 'details': str(e)}), 500

# ==================== ENVIAR A TODOS LOS USUARIOS ====================
@app.route('/api/notifications/send-to-all', methods=['POST'])
def send_to_all():
    try:
        data = request.get_json()
        
        if not data.get('title') or not data.get('body'):
            return jsonify({
                'error': 'Faltan datos requeridos',
                'required': ['title', 'body']
            }), 400
        
        title = data['title']
        body = data['body']
        notification_data = data.get('data', {})
        
        print(f'📤 Enviando notificación a todos los usuarios...')
        
        # Obtener todos los tokens
        users_ref = db.collection('usuarios_registrados')
        users = users_ref.where('fcmToken', '!=', None).stream()
        
        tokens = []
        for user in users:
            user_data = user.to_dict()
            fcm_token = user_data.get('fcmToken')
            if fcm_token:
                tokens.append(fcm_token)
        
        if not tokens:
            return jsonify({'error': 'No hay usuarios con tokens FCM'}), 400
        
        print(f'📱 Total de tokens: {len(tokens)}')
        
        # Enviar en lotes de 500
        batch_size = 500
        total_success = 0
        total_failure = 0
        
        for i in range(0, len(tokens), batch_size):
            batch = tokens[i:i + batch_size]
            
            message = messaging.MulticastMessage(
                notification=messaging.Notification(title=title, body=body),
                data=notification_data,
                tokens=batch,
            )
            
            response = messaging.send_multicast(message)
            total_success += response.success_count
            total_failure += response.failure_count
        
        print(f'✅ {total_success} enviadas, {total_failure} fallidas')
        
        return jsonify({
            'success': True,
            'message': 'Notificaciones enviadas',
            'totalUsers': len(tokens),
            'successCount': total_success,
            'failureCount': total_failure,
        })
        
    except Exception as e:
        print(f'❌ Error: {str(e)}')
        return jsonify({'error': str(e)}), 500

# ==================== ENVIAR A UN TÓPICO ====================
@app.route('/api/notifications/send-to-topic', methods=['POST'])
def send_to_topic():
    try:
        data = request.get_json()
        
        if not data.get('topic') or not data.get('title') or not data.get('body'):
            return jsonify({
                'error': 'Faltan datos requeridos',
                'required': ['topic', 'title', 'body']
            }), 400
        
        topic = data['topic']
        title = data['title']
        body = data['body']
        notification_data = data.get('data', {})
        
        message = messaging.Message(
            notification=messaging.Notification(title=title, body=body),
            data=notification_data,
            topic=topic,
            android=messaging.AndroidConfig(
                priority='high',
                notification=messaging.AndroidNotification(
                    sound='default',
                    channel_id='general_channel',
                ),
            ),
        )
        
        response = messaging.send(message)
        
        return jsonify({
            'success': True,
            'message': 'Notificación enviada al tópico',
            'messageId': response,
            'topic': topic
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ==================== LISTAR USUARIOS ====================
@app.route('/api/notifications/users', methods=['GET'])
def get_users():
    try:
        users_ref = db.collection('usuarios_registrados')
        users = users_ref.stream()
        
        users_list = []
        for user in users:
            user_data = user.to_dict()
            users_list.append({
                'id': user.id,
                'email': user_data.get('email'),
                'hasToken': bool(user_data.get('fcmToken')),
            })
        
        with_tokens = sum(1 for u in users_list if u['hasToken'])
        
        return jsonify({
            'success': True,
            'total': len(users_list),
            'withTokens': with_tokens,
            'users': users_list
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ==================== EJECUTAR SERVIDOR ====================
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    
    print('\n╔════════════════════════════════════════════╗')
    print('║  SERVIDOR DE NOTIFICACIONES PUSH - FLASK  ║')
    print('╚════════════════════════════════════════════╝\n')
    print(f'🚀 Servidor corriendo en puerto: {port}')
    print('📡 API lista para recibir peticiones')
    print('\n✅ Presiona Ctrl+C para detener\n')
    
    # En producción, usar gunicorn (no debug mode)
    app.run(host='0.0.0.0', port=port, debug=False)