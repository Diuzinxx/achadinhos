import os
import sqlite3
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, abort

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "troque-esta-chave-em-producao")
DATABASE = os.environ.get("DATABASE_PATH", os.path.join(os.path.dirname(__file__), "products.db"))
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")

CATEGORIES = ["Todos","Roupas","Calçados","Acessórios","Casa","Beleza","Academia","Presentes","Ofertas"]

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute("""CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, price TEXT NOT NULL,
        old_price TEXT, category TEXT NOT NULL, image_url TEXT NOT NULL,
        affiliate_url TEXT NOT NULL, description TEXT, featured INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(products)").fetchall()}
    if "store" not in cols:
        conn.execute("ALTER TABLE products ADD COLUMN store TEXT DEFAULT 'Shopee'")
    if "clicks" not in cols:
        conn.execute("ALTER TABLE products ADD COLUMN clicks INTEGER DEFAULT 0")
    conn.commit(); conn.close()

def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("admin_login"))
        return view(*args, **kwargs)
    return wrapped

@app.context_processor
def globals():
    return {"categories": CATEGORIES}

@app.route("/")
def index():
    q = request.args.get("q","").strip()
    category = request.args.get("categoria","Todos").strip()
    conn = get_db()
    sql = "SELECT * FROM products WHERE 1=1"
    params = []
    if q:
        sql += " AND (name LIKE ? OR description LIKE ? OR category LIKE ? OR store LIKE ?)"
        x=f"%{q}%"; params += [x,x,x,x]
    if category != "Todos":
        sql += " AND category=?"; params.append(category)
    sql += " ORDER BY featured DESC, created_at DESC"
    products = conn.execute(sql,params).fetchall()
    featured = conn.execute("SELECT * FROM products WHERE featured=1 ORDER BY created_at DESC LIMIT 8").fetchall()
    most_clicked = conn.execute("SELECT * FROM products ORDER BY clicks DESC, created_at DESC LIMIT 8").fetchall()
    conn.close()
    return render_template("index.html", products=products, featured=featured, most_clicked=most_clicked, q=q, selected_category=category)

@app.route("/produto/<int:product_id>")
def product(product_id):
    conn=get_db()
    item=conn.execute("SELECT * FROM products WHERE id=?",(product_id,)).fetchone()
    if not item: conn.close(); abort(404)
    related=conn.execute("SELECT * FROM products WHERE category=? AND id!=? ORDER BY featured DESC, created_at DESC LIMIT 4",(item["category"],product_id)).fetchall()
    conn.close()
    return render_template("product.html",product=item,related=related)

@app.route("/go/<int:product_id>")
def go(product_id):
    conn=get_db(); item=conn.execute("SELECT affiliate_url FROM products WHERE id=?",(product_id,)).fetchone()
    if not item: conn.close(); abort(404)
    conn.execute("UPDATE products SET clicks=COALESCE(clicks,0)+1 WHERE id=?",(product_id,))
    conn.commit(); conn.close()
    return redirect(item["affiliate_url"])

@app.route("/sobre")
def about(): return render_template("about.html")

@app.route("/admin/login",methods=["GET","POST"])
def admin_login():
    if request.method=="POST":
        if request.form.get("password")==ADMIN_PASSWORD:
            session["admin"]=True; return redirect(url_for("admin"))
        flash("Senha incorreta.","error")
    return render_template("admin_login.html")

@app.route("/admin/logout")
def admin_logout(): session.clear(); return redirect(url_for("index"))

@app.route("/admin")
@admin_required
def admin():
    conn=get_db()
    products=conn.execute("SELECT * FROM products ORDER BY created_at DESC").fetchall()
    stats={
        "products":conn.execute("SELECT COUNT(*) n FROM products").fetchone()["n"],
        "featured":conn.execute("SELECT COUNT(*) n FROM products WHERE featured=1").fetchone()["n"],
        "clicks":conn.execute("SELECT COALESCE(SUM(clicks),0) n FROM products").fetchone()["n"]}
    conn.close()
    return render_template("admin.html",products=products,stats=stats)

def form_data():
    f=request.form
    return dict(name=f.get("name","").strip(),price=f.get("price","").strip(),old_price=f.get("old_price","").strip(),
        category=f.get("category","Ofertas"),image_url=f.get("image_url","").strip(),affiliate_url=f.get("affiliate_url","").strip(),
        description=f.get("description","").strip(),featured=1 if f.get("featured") else 0,store=f.get("store","Shopee").strip() or "Shopee")

@app.route("/admin/produto/novo",methods=["GET","POST"])
@admin_required
def new_product():
    if request.method=="POST":
        d=form_data()
        if not d["name"] or not d["price"] or not d["image_url"] or not d["affiliate_url"]:
            flash("Preencha nome, preço, imagem e link de afiliado.","error")
            return render_template("product_form.html",product=None)
        conn=get_db()
        conn.execute("""INSERT INTO products(name,price,old_price,category,image_url,affiliate_url,description,featured,store)
                        VALUES(?,?,?,?,?,?,?,?,?)""",(d["name"],d["price"],d["old_price"],d["category"],d["image_url"],d["affiliate_url"],d["description"],d["featured"],d["store"]))
        conn.commit(); conn.close(); flash("Produto adicionado!","success"); return redirect(url_for("admin"))
    return render_template("product_form.html",product=None)

@app.route("/admin/produto/<int:product_id>/editar",methods=["GET","POST"])
@admin_required
def edit_product(product_id):
    conn=get_db(); item=conn.execute("SELECT * FROM products WHERE id=?",(product_id,)).fetchone()
    if not item: conn.close(); abort(404)
    if request.method=="POST":
        d=form_data()
        conn.execute("""UPDATE products SET name=?,price=?,old_price=?,category=?,image_url=?,affiliate_url=?,description=?,featured=?,store=? WHERE id=?""",
                     (d["name"],d["price"],d["old_price"],d["category"],d["image_url"],d["affiliate_url"],d["description"],d["featured"],d["store"],product_id))
        conn.commit(); conn.close(); flash("Produto atualizado!","success"); return redirect(url_for("admin"))
    conn.close(); return render_template("product_form.html",product=item)

@app.route("/admin/produto/<int:product_id>/excluir",methods=["POST"])
@admin_required
def delete_product(product_id):
    conn=get_db(); conn.execute("DELETE FROM products WHERE id=?",(product_id,)); conn.commit(); conn.close()
    flash("Produto excluído.","success"); return redirect(url_for("admin"))

if __name__=="__main__":
    init_db()
    app.run(debug=True)
