import re, sqlite3, unicodedata

OWNER_ID = 7364435907
DB_FILE = "escrow.db"
LAST_PIN = None

def db_run(q, p=(), fetch=None):
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute(q, p)
        res = c.fetchall() if fetch == "all" else (c.fetchone() if fetch == "one" else None)
        conn.commit()
        return res

db_run('CREATE TABLE IF NOT EXISTS deals (did TEXT PRIMARY KEY, status TEXT, seller TEXT, buyer TEXT, amt REAL, fee REAL, escrower TEXT, msg_id INTEGER)')
db_run('CREATE TABLE IF NOT EXISTS stats (id INTEGER PRIMARY KEY, deals INTEGER, vol REAL, fees REAL)')
db_run('CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v INTEGER)')
db_run('INSERT OR IGNORE INTO stats VALUES (1, 0, 0.0, 0.0)')
db_run('INSERT OR IGNORE INTO meta VALUES ("ctr", 11254)')

def get_next_did():
    curr = db_run('SELECT v FROM meta WHERE k = "ctr"', fetch="one")[0]
    db_run('UPDATE meta SET v = ? WHERE k = "ctr"', (curr + 1,))
    return f"DL-CHIKU-{curr}"

MAP = {'ɢ':'g','ɪ':'i','ɴ':'n','ʀ':'r','ʏ':'y','ʙ':'b','ʜ':'h','ʟ':'l','ꜱ':'s','ғ':'f','ᴀ':'a','ᴄ':'c','ᴅ':'d','ᴇ':'e','ᴋ':'k','ᴍ':'m','ᴏ':'o','ᴘ':'p','ᴛ':'t','ᴜ':'u','ᴡ':'w','ᴊ':'j','ǫ':'q','ᴠ':'v','ᴢ':'z','𝖴':'u','U':'u','O':'o','О':'o','а':'a','е':'e','о':'o','р':'p','с':'c','у':'y','х':'x','м':'m','н':'n','т':'t'}

def clean_txt(t):
    return "".join(MAP.get(ch, ch) for ch in unicodedata.normalize('NFKD', str(t or ""))).lower()

def calc_fee(amt):
    if amt <= 0: return 0.0, "0%", "0₹", 0.0
    if amt <= 190: return 10.0, "Flat ₹10", "Rs 10", amt - 10.0
    if amt <= 599: return 20.0, "Flat ₹20", "Rs 20", amt - 20.0
    if amt <= 2000:
        f = round(amt * 0.035, 2)
        return f, "3.5%", f"3.5% - {round(f)}₹", amt - f
    f = round(amt * 0.03, 2)
    return f, "3%", f"3% - {round(f)}₹", amt - f

def parse_form(raw):
    d = {"seller": "", "buyer": "", "details": "", "amount": 0.0, "till": "", "id": ""}
    if not raw: return d
    cf = clean_txt(raw)
    m_id = re.search(r"dl[-_ ]*chiku[-_ ]*(\d+)", cf, re.I)
    if m_id: d["id"] = f"DL-CHIKU-{m_id.group(1)}"
    rl, cl = raw.split('\n'), cf.split('\n')
    for i, (r, c) in enumerate(zip(rl, cl)):
        if not c.strip(): continue
        val = r.split(':', 1)[1].strip() if ':' in r else (r.split('-', 1)[1].strip() if '-' in r else "")
        lbl = re.sub(r'^[•\*\-\s]+', '', c.split(':', 1)[0] if ':' in c else c.split('-', 1)[0]).strip()
        if (lbl in ['seller', 's'] or lbl.endswith(' seller')) and not d['seller']: d['seller'] = val
        elif (lbl in ['buyer', 'b'] or lbl.endswith(' buyer')) and not d['buyer']: d['buyer'] = val
        elif any(k in lbl for k in ['detail', 'deatail']) and not d['details']:
            d['details'] = val
            if i + 1 < len(rl) and cl[i+1].strip() and not any(k in cl[i+1] for k in ['•','*','-',':','amount','amt','till','escrow']):
                d['details'] += " " + rl[i+1].strip()
        elif any(k in lbl for k in ['amount', 'amt', 'price', 'cost']) and d['amount'] == 0.0:
            m = re.search(r'(\d+(?:\.\d+)?)', clean_txt(val).replace(',', ''))
            if m: d['amount'] = float(m.group(1))
        elif 'till' in lbl and not d['till']: d['till'] = val
    if d['amount'] == 0.0:
        no_u = re.sub(r'@\w+', '', cf).replace(',', '')
        m_amt = re.search(r'(?:amount|amt|price)[\s\:\-]*[₹rs\s]*(\d+(?:\.\d+)?)', no_u) or re.search(r'[₹rs]\s*(\d+(?:\.\d+)?)', no_u)
        if m_amt: d['amount'] = float(m_amt.group(1))
    return d

async def resolve_u(u, rep, ctx, cid):
    if not u or u.upper() == "N/A": return u or "N/A"
    clean = u.strip()
    if "(" in clean and ")" in clean: return clean
    if clean.isdigit(): return f'<a href="tg://user?id={clean}">{clean}</a> ({clean})'
    if clean.lower() in ["me", "i", "myself", "mai"] and rep and rep.from_user:
        fu = rep.from_user
        return f"@{fu.username} ({fu.id})" if fu.username else f"{fu.first_name} ({fu.id})"
    if rep and rep.entities:
        for ent in rep.entities:
            if ent.type == "text_mention" and ent.user: return f'{ent.user.mention_html()} ({ent.user.id})'
    if clean.startswith("@"):
        try:
            m = await ctx.bot.get_chat_member(cid, clean)
            if m and m.user: return f"{clean} ({m.user.id})"
        except: pass
    return clean
        
