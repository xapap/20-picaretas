import streamlit as st
import streamlit.components.v1 as components
import sqlite3
import hashlib
from datetime import datetime, timedelta

# Configuração da página
st.set_page_config(page_title="20 Picaretas", page_icon="⛏️", layout="centered")

# --- PARÂMETROS ECONÓMICOS ---
TOTAL_CAP = 2100000.0   # Teto mundial: 2.1 Milhões
CUSTO_PREMIO = 50000.0  # Meta para o Vale de 20€ / Fruta (aprox. 400 visitas)
BONUS_BOAS_VINDAS = 1000.0

# --- SEGURANÇA ---
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

# --- BASE DE DADOS (SQLite com Auto-Migração) ---
def init_db():
    conn = sqlite3.connect("jogo.db")
    c = conn.cursor()
    
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password_hash TEXT,
            balance REAL DEFAULT 0,
            streak INTEGER DEFAULT 0,
            last_mine TIMESTAMP,
            created_at TIMESTAMP
        )
    """)
    
    # Auto-migração caso existam tabelas de versões anteriores
    c.execute("PRAGMA table_info(users)")
    colunas = [col[1] for col in c.fetchall()]
    if "password_hash" not in colunas:
        c.execute("ALTER TABLE users ADD COLUMN password_hash TEXT DEFAULT ''")
    if "created_at" not in colunas:
        c.execute("ALTER TABLE users ADD COLUMN created_at TIMESTAMP")

    c.execute("""
        CREATE TABLE IF NOT EXISTS global_state (
            id INTEGER PRIMARY KEY,
            total_mined REAL DEFAULT 0
        )
    """)
    c.execute("INSERT OR IGNORE INTO global_state (id, total_mined) VALUES (1, 0)")
    
    c.execute("""
        CREATE TABLE IF NOT EXISTS claims (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            reward_type TEXT,
            store_choice TEXT,
            claimed_at TIMESTAMP,
            status TEXT DEFAULT 'Pendente'
        )
    """)
    
    conn.commit()
    conn.close()

init_db()

# --- LÓGICA DE JOGO E PATENTES ---
def get_rank_title(balance):
    if balance >= 50000:
        return "👑 Lenda das 20 Picaretas"
    elif balance >= 35000:
        return "💎 Almirante de Diamante"
    elif balance >= 15000:
        return "🥇 Mestre de Ouro"
    elif balance >= 5000:
        return "🥈 Mineiro de Prata"
    elif balance >= 1000:
        return "🥉 Mineiro de Cobre"
    return "🌱 Aprendiz de Picareta"

def authenticate(username, password):
    conn = sqlite3.connect("jogo.db")
    c = conn.cursor()
    pwd_hash = hash_password(password)
    c.execute("SELECT username FROM users WHERE LOWER(username) = LOWER(?) AND password_hash = ?", (username, pwd_hash))
    user = c.fetchone()
    conn.close()
    return user[0] if user else None

def register_user(username, password):
    username = username.strip()
    if len(username) < 3:
        return False, "O nome deve ter pelo menos 3 caracteres."
    if len(password) < 4:
        return False, "A palavra-passe deve ter pelo menos 4 caracteres."
    
    conn = sqlite3.connect("jogo.db")
    c = conn.cursor()
    c.execute("SELECT username FROM users WHERE LOWER(username) = LOWER(?)", (username,))
    if c.fetchone():
        conn.close()
        return False, "Esse nome já existe na mina. Escolhe outro ou faz login."
    
    pwd_hash = hash_password(password)
    now = datetime.now().isoformat()
    c.execute("""
        INSERT INTO users (username, password_hash, balance, streak, last_mine, created_at)
        VALUES (?, ?, 0, 0, NULL, ?)
    """, (username, pwd_hash, now))
    conn.commit()
    conn.close()
    return True, "Registo concluído com sucesso!"

def get_user_data(username):
    conn = sqlite3.connect("jogo.db")
    c = conn.cursor()
    c.execute("SELECT balance, streak, last_mine FROM users WHERE username = ?", (username,))
    row = c.fetchone()
    conn.close()
    return row

def get_global_mined():
    conn = sqlite3.connect("jogo.db")
    c = conn.cursor()
    c.execute("SELECT total_mined FROM global_state WHERE id = 1")
    val = c.fetchone()[0]
    conn.close()
    return val

def calculate_reward(global_mined):
    base_reward = 110.0 / (1.0 + (global_mined / 500000.0))
    return round(base_reward, 2)

def execute_mine(username):
    conn = sqlite3.connect("jogo.db")
    c = conn.cursor()
    
    c.execute("SELECT streak, last_mine, balance FROM users WHERE username = ?", (username,))
    streak, last_mine_str, balance = c.fetchone()
    
    now = datetime.now()
    bonus_welcome = 0.0
    
    if last_mine_str is None:
        new_streak = 1
        bonus_welcome = BONUS_BOAS_VINDAS # Bónus de arranque imediato
    else:
        last_mine = datetime.fromisoformat(last_mine_str)
        diff = now - last_mine
        if diff < timedelta(hours=24):
            conn.close()
            return False, "A rocha ainda está quente! Volta quando passarem as 24 horas."
        elif diff <= timedelta(hours=48):
            new_streak = streak + 1
        else:
            new_streak = 1
            
    c.execute("SELECT total_mined FROM global_state WHERE id = 1")
    global_mined = c.fetchone()[0]
    
    base = calculate_reward(global_mined)
    bonus_streak = min((new_streak - 1) * 0.01, 0.25)
    multiplier = 1.0 + bonus_streak
    reward_mined = round(base * multiplier, 2)
    
    total_ganho = reward_mined + bonus_welcome
    new_balance = round(balance + total_ganho, 2)
    
    c.execute("UPDATE users SET balance = ?, streak = ?, last_mine = ? WHERE username = ?", 
              (new_balance, new_streak, now.isoformat(), username))
    c.execute("UPDATE global_state SET total_mined = total_mined + ? WHERE id = 1", (reward_mined,))
    
    conn.commit()
    conn.close()
    
    if bonus_welcome > 0:
        return True, f"Bónus de Boas-Vindas (+{bonus_welcome:.0f}) + Picareta (+{reward_mined:.2f}) = +{total_ganho:.2f} Fragmentos!"
    return True, f"Extraíste +{reward_mined:.2f} Fragmentos! (Sequência {new_streak} dias 🔥)"

def claim_reward(username, reward_choice, store_choice):
    conn = sqlite3.connect("jogo.db")
    c = conn.cursor()
    c.execute("SELECT balance FROM users WHERE username = ?", (username,))
    balance = c.fetchone()[0]
    
    if balance < CUSTO_PREMIO:
        conn.close()
        return False, "Ainda não tens fragmentos suficientes!"
        
    new_balance = round(balance - CUSTO_PREMIO, 2)
    c.execute("UPDATE users SET balance = ? WHERE username = ?", (new_balance, username))
    now = datetime.now().isoformat()
    c.execute("""
        INSERT INTO claims (username, reward_type, store_choice, claimed_at, status)
        VALUES (?, ?, ?, ?, 'Pendente')
    """, (username, reward_choice, store_choice, now))
    conn.commit()
    conn.close()
    return True, "Pedido de prémio registado! Entraremos em contacto para a entrega."

def get_leaderboard():
    conn = sqlite3.connect("jogo.db")
    c = conn.cursor()
    c.execute("SELECT username, balance, streak FROM users ORDER BY balance DESC LIMIT 5")
    rows = c.fetchall()
    conn.close()
    return rows

# --- INTERFACE PRINCIPAL ---
st.title("⛏️ 20 Picaretas")
st.caption("A reserva finita de minério. Dá o teu golpe diário e junta para o teu vale.")

# ABAS: JOGO vs GUIA EXPLICATIVO
tab_jogo, tab_guia = st.tabs(["🎮 A Mina", "📖 Como Funciona (Lê Aqui)"])

# ==========================================
# ABA 1: O JOGO
# ==========================================
with tab_jogo:
    # Estado da Reserva Global
    global_mined = get_global_mined()
    progresso_global = min(global_mined / TOTAL_CAP, 1.0)
    st.progress(progresso_global)
    st.caption(f"🌍 Jazida Global: **{global_mined:,.2f}** / **{TOTAL_CAP:,.0f}** Fragmentos extraídos ({progresso_global*100:.2f}%)")
    
    st.divider()

    # Sessão de Utilizador
    if "logged_user" not in st.session_state:
        st.session_state.logged_user = None

    if not st.session_state.logged_user:
        aba_log, aba_reg = st.tabs(["🔑 Entrar na Conta", "📝 Novo Mineiro"])
        
        # Nota de privacidade diretamente por baixo das abas
        st.caption("🔒 Só precisamos de uma alcunha e uma palavra-passe — **não pedimos nem precisamos do teu e-mail**.")
        
        with aba_log:
            l_user = st.text_input("Alcunha:", key="log_u")
            l_pass = st.text_input("Palavra-passe:", type="password", key="log_p")
            if st.button("Entrar", type="primary"):
                user = authenticate(l_user, l_pass)
                if user:
                    st.session_state.logged_user = user
                    st.rerun()
                else:
                    st.error("Alcunha ou palavra-passe errada.")
                    
        with aba_reg:
            r_user = st.text_input("Escolhe a tua Alcunha:", key="reg_u")
            r_pass = st.text_input("Palavra-passe:", type="password", key="reg_p")
            if st.button("Criar Conta e Ganhar +1.000 Bónus"):
                ok, msg = register_user(r_user, r_pass)
                if ok:
                    st.success(msg + " Vai à aba 'Entrar na Conta'.")
                else:
                    st.warning(msg)
    else:
        username = st.session_state.logged_user
        balance, streak, last_mine_str = get_user_data(username)
        rank = get_rank_title(balance)
        
        # Painel do Jogador
        top_c1, top_c2 = st.columns([3, 1])
        top_c1.markdown(f"### Mineiro: **{username}**")
        top_c1.caption(f"Patente Atual: **{rank}**")
        if top_c2.button("Sair"):
            st.session_state.logged_user = None
            st.rerun()
            
        # Validação 24 Horas e contagem
        pode_minerar = True
        segundos_restantes = 0
        tempo_str = ""
        
        if last_mine_str:
            last_mine = datetime.fromisoformat(last_mine_str)
            proxima = last_mine + timedelta(hours=24)
            agora = datetime.now()
            if agora < proxima:
                pode_minerar = False
                restante = proxima - agora
                segundos_restantes = max(0, int(restante.total_seconds()))
                h, r = divmod(segundos_restantes, 3600)
                m, _ = divmod(r, 60)
                tempo_str = f"{h}h {m}m"

        # Métricas em 3 Colunas com Countdown ao Vivo
        m1, m2, m3 = st.columns(3)
        m1.metric("O teu Saldo", f"{balance:,.2f} 💎")
        
        # Correção do plural ("1 dia" vs "2 dias")
        texto_dias = "dia" if streak == 1 else "dias"
        m2.metric("Sequência Diária", f"{streak} {texto_dias} 🔥")
        
        with m3:
            if pode_minerar:
                st.metric("Próxima Picareta", "Disponível! ⚡")
            else:
                # Componente HTML/JS para contagem regressiva em direto segundo a segundo
                countdown_html = f"""
                <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
                    <div style="font-size: 14px; color: #808495; margin-bottom: 4px;">Próxima Picareta</div>
                    <div id="countdown" style="font-size: 26px; font-weight: 700; color: #ff4b4b; line-height: 1.2;">
                        Calculando...
                    </div>
                </div>
                <script>
                    let timeLeft = {segundos_restantes};
                    function updateTimer() {{
                        if (timeLeft <= 0) {{
                            document.getElementById("countdown").innerHTML = "Disponível! ⚡";
                            document.getElementById("countdown").style.color = "#09ab3b";
                            return;
                        }}
                        const h = Math.floor(timeLeft / 3600);
                        const m = Math.floor((timeLeft % 3600) / 60);
                        const s = timeLeft % 60;
                        const hStr = h > 0 ? h + "h " : "";
                        const mStr = (m < 10 ? "0" + m : m) + "m ";
                        const sStr = (s < 10 ? "0" + s : s) + "s";
                        document.getElementById("countdown").innerHTML = "⏳ " + hStr + mStr + sStr;
                        timeLeft--;
                    }}
                    updateTimer();
                    setInterval(updateTimer, 1000);
                </script>
                """
                components.html(countdown_html, height=75)

        recompensa_prox = calculate_reward(global_mined) * (1.0 + min(streak * 0.01, 0.25))
        st.write(f"Estimativa do próximo golpe: **+{recompensa_prox:.2f} fragmentos**")
        
        if pode_minerar:
            if streak == 0:
                st.info("🎁 **Primeiro Golpe Especial:** Ganhas +1.000 Fragmentos de bónus de arranque!")
            if st.button("⛏️ DAR O GOLPE DE HOJE", type="primary", use_container_width=True):
                ok, msg = execute_mine(username)
                if ok:
                    st.balloons()
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)
        else:
            st.button(f"⏳ Picareta em Arrefecimento (Volta em {tempo_str})", disabled=True, use_container_width=True)
            st.caption("A terra precisa de 24 horas para regenerar. Não deixes o fogo da sequência apagar-se!")

        # --- ÁREA DE RESGATE / VALE DE 20 PICARETAS ---
        st.divider()
        st.subheader("🎁 Resgate: O Vale de 20 Picaretas")
        
        progresso_meta = min(balance / CUSTO_PREMIO, 1.0)
        st.write(f"Caminho até ao Prémio: **{balance:,.1f}** / **{CUSTO_PREMIO:,.0f} fragmentos** ({progresso_meta*100:.1f}%)")
        st.progress(progresso_meta)
        
        col_tipo, col_loja = st.columns(2)
        with col_tipo:
            tipo_premio = st.selectbox("Tipo de Recompensa:", ["Vale de 20€ (20 Picaretas)", "1 Kg de Fruta Fresca à Escolha"])
        with col_loja:
            if "Vale" in tipo_premio:
                loja = st.selectbox("Loja à Tua Escolha:", ["Pingo Doce", "Continente", "Amazon", "Fnac", "Outra Loja"])
            else:
                loja = st.text_input("Que fruta preferes?", placeholder="Ex: Bananas, Maçãs de Alcobaça, Laranjas")
                
        if balance >= CUSTO_PREMIO:
            if st.button("🎉 RESGATAR O MEU PRÉMIO AGORA", type="secondary", use_container_width=True):
                ok, msg = claim_reward(username, tipo_premio, loja)
                if ok:
                    st.balloons()
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)
        else:
            faltam = CUSTO_PREMIO - balance
            st.button(f"🔒 Bloqueado (Faltam {faltam:,.1f} fragmentos)", disabled=True, use_container_width=True)

    # Leaderboard
    st.divider()
    st.subheader("🏆 Pódio dos Melhores Mineiros")
    lboard = get_leaderboard()
    if lboard:
        dados = [
            {"Posição": f"#{i+1}", "Mineiro": r[0], "Patente": get_rank_title(r[1]), "Saldo": f"{r[1]:,.2f} 💎", "Sequência": f"{r[2]} dias 🔥"}
            for i, r in enumerate(lboard)
        ]
        st.table(dados)
    else:
        st.caption("Ainda ninguém deu a primeira picareta.")

# ==========================================
# ABA 2: O GUIA EXPLICATIVO COMPLETO
# ==========================================
with tab_guia:
    st.header("📖 O Que É o '20 Picaretas'?")
    st.write("""
    O **20 Picaretas** é uma experiência comunitária diária inspirada nos grandes fenómenos asiáticos de retenção e escassez digital.
    
    O conceito é simples: **consistência vale ouro**. Quem entra todos os dias e mantém a sua picareta ativa vai acumulando fragmentos reais até levar para casa um prémio físico ou digital.
    """)
    
    st.subheader("🎯 As Regras de Ouro")
    st.markdown("""
    1. **1 Golpe a Cada 24 Horas:** Não adianta tentar carregar 50 vezes seguidas. A rocha precisa de 24 horas completas para arrefecer.
    2. **A Reserva Finita de 2,1 Milhões:** Tal como o ouro ou o Bitcoin, os fragmentos do mundo são finitos. Quanto mais fragmentos forem minerados pela comunidade, mais difícil e raro se torna cada golpe.
    3. **A Sequência de Fogo (Streak):** Cada dia seguido que voltas dá-te um bónus cumulativo (até +25%). Se passares mais de 48 horas sem cá vir, a sequência apaga-se e volta a 1.
    4. **O Bónus de Boas-Vindas:** Logo na tua primeira picareta, recebes de imediato **+1.000 Fragmentos** para arrancar na frente.
    """)
    
    st.subheader("🎁 O Prémio Final: O 'Vale de 20 Picaretas'")
    st.write("""
    Ao atingires a marca dos **50.000 Fragmentos**, o botão de resgate é desbloqueado e podes escolher:
    * **Vale de Compras de 20€** numa loja à tua escolha (Pingo Doce, Continente, Amazon, Fnac, etc.).
    * **1 Kg de Fruta Fresca à tua escolha** entregue diretamente.
    """)
    
    st.subheader("🎖️ Patentes Disponíveis")
    st.markdown("""
    À medida que o teu saldo sobe, a tua patente no ranking muda automaticamente:
    * 🌱 **Aprendiz de Picareta** (0 a 999 💎)
    * 🥉 **Mineiro de Cobre** (1.000 a 4.999 💎)
    * 🥈 **Mineiro de Prata** (5.000 a 14.999 💎)
    * 🥇 **Mestre de Ouro** (15.000 a 34.999 💎)
    * 💎 **Almirante de Diamante** (35.000 a 49.999 💎)
    * 👑 **Lenda das 20 Picaretas** (50.000+ 💎 — *Prémio Desbloqueado!*)
    """)