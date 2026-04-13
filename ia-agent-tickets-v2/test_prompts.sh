#!/usr/bin/env bash
# Test de flujo completo — creador reporta un problema
# Verifica que los prompts reducidos funcionan correctamente

AGENT="http://localhost:8001"
KEY="dev-key-change-in-prod"
THREAD="test-$(date +%s)"
USER_ID=1
ROLE="creador"

send() {
  local turn=$1
  local msg=$2
  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "TURNO $turn — Usuario: $msg"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  response=$(curl -s -X POST "$AGENT/agent/chat" \
    -H "Content-Type: application/json" \
    -H "X-Agent-Key: $KEY" \
    -d "{\"user_id\":$USER_ID,\"user_rol\":\"$ROLE\",\"message\":\"$msg\",\"thread_id\":\"$THREAD\"}")
  echo "$response" | python3 -c "import sys,json; d=json.load(sys.stdin); print('Agente:', d.get('reply','ERROR:'+str(d)))"
}

echo "============================================"
echo " TEST: Flujo creación de ticket (rol=creador)"
echo " Thread: $THREAD"
echo "============================================"

send 1 "Hola, mi impresora no funciona, no imprime nada"
sleep 3

send 2 "No, ninguna de esas soluciones me aplica, necesito crear un ticket"
sleep 3

send 3 "Es un incidente, la impresora del tercer piso simplemente no responde"
sleep 3

send 4 "Hardware, impresoras"
sleep 3

send 5 "La urgencia es alta"
sleep 3

send 6 "Sí, confirmo la creación del ticket"
sleep 2

echo ""
echo "============================================"
echo " Verificando ticket en el backend..."
echo "============================================"
curl -s "http://localhost:8000/api/tickets?created_by=1" | python3 -c "
import sys, json
tickets = json.load(sys.stdin)
print(f'Total tickets del usuario 1: {len(tickets)}')
for t in tickets[-3:]:
    print(f'  → ID={t[\"id\"]} | Estado={t.get(\"stage_id\",\"?\")} | Desc={t[\"descripcion\"][:60]}')
"
