from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session, g
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date, timedelta
from sqlalchemy import func
import os
import secrets
import string

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'odonto-crm-secret-2024')

db_url = os.environ.get('DATABASE_URL', 'sqlite:///odonto.db')
if db_url.startswith('postgres://'):
    db_url = db_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

ADMIN_EMAIL = 'admin@odontcrm.com'

# ─── Models ───────────────────────────────────────────────────────────────────

class Clinic(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    cnpj = db.Column(db.String(18), unique=True)
    plan = db.Column(db.String(20), default='free')  # free, basic, premium
    status = db.Column(db.String(20), default='active')  # active, suspended, cancelled
    admin_email = db.Column(db.String(120))
    invite_token = db.Column(db.String(32), unique=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    users = db.relationship('User', backref='clinic', lazy=True, cascade='all, delete-orphan')
    patients = db.relationship('Patient', backref='clinic', lazy=True, cascade='all, delete-orphan')


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    clinic_id = db.Column(db.Integer, db.ForeignKey('clinic.id'))  # None = admin global
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256))
    name = db.Column(db.String(120))
    role = db.Column(db.String(20), default='dentist')  # admin (global), owner, dentist, receptionist
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self):
        return self.role == 'admin'

    @property
    def is_owner(self):
        return self.clinic_id is not None and self.role == 'owner'


class Patient(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    clinic_id = db.Column(db.Integer, db.ForeignKey('clinic.id'), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    cpf = db.Column(db.String(14))
    birth_date = db.Column(db.Date)
    phone = db.Column(db.String(20))
    email = db.Column(db.String(120))
    address = db.Column(db.String(200))
    allergies = db.Column(db.Text)
    bruxism = db.Column(db.Boolean, default=False)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    appointments = db.relationship('Appointment', backref='patient', lazy=True, cascade='all, delete-orphan')
    treatments = db.relationship('Treatment', backref='patient', lazy=True, cascade='all, delete-orphan')
    payments = db.relationship('Payment', backref='patient', lazy=True, cascade='all, delete-orphan')
    teeth = db.relationship('Tooth', backref='patient', lazy=True, cascade='all, delete-orphan')

    @property
    def age(self):
        if self.birth_date:
            today = date.today()
            return today.year - self.birth_date.year - ((today.month, today.day) < (self.birth_date.month, self.birth_date.day))
        return None


class Dentist(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    clinic_id = db.Column(db.Integer, db.ForeignKey('clinic.id'), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    cro = db.Column(db.String(20))
    specialties = db.Column(db.String(200))
    phone = db.Column(db.String(20))
    email = db.Column(db.String(120))
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    appointments = db.relationship('Appointment', backref='dentist', lazy=True)
    treatments = db.relationship('Treatment', backref='dentist', lazy=True)


class Appointment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    clinic_id = db.Column(db.Integer, db.ForeignKey('clinic.id'), nullable=False)
    patient_id = db.Column(db.Integer, db.ForeignKey('patient.id'), nullable=False)
    dentist_id = db.Column(db.Integer, db.ForeignKey('dentist.id'))
    date = db.Column(db.Date, nullable=False)
    time = db.Column(db.Time, nullable=False)
    duration = db.Column(db.Integer, default=30)
    type = db.Column(db.String(50))
    status = db.Column(db.String(20), default='Agendado')
    reason = db.Column(db.Text)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def datetime_str(self):
        return f"{self.date.strftime('%d/%m/%Y')} às {self.time.strftime('%H:%M')}"


class Treatment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    clinic_id = db.Column(db.Integer, db.ForeignKey('clinic.id'), nullable=False)
    patient_id = db.Column(db.Integer, db.ForeignKey('patient.id'), nullable=False)
    dentist_id = db.Column(db.Integer, db.ForeignKey('dentist.id'))
    name = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(20), default='Proposta')
    start_date = db.Column(db.Date)
    estimated_end = db.Column(db.Date)
    end_date = db.Column(db.Date)
    total_cost = db.Column(db.Float)
    paid_amount = db.Column(db.Float, default=0)
    sessions_planned = db.Column(db.Integer)
    sessions_completed = db.Column(db.Integer, default=0)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def remaining_cost(self):
        return (self.total_cost or 0) - (self.paid_amount or 0)

    @property
    def progress(self):
        if not self.sessions_planned:
            return 0
        return int((self.sessions_completed / self.sessions_planned) * 100)


class Tooth(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    clinic_id = db.Column(db.Integer, db.ForeignKey('clinic.id'), nullable=False)
    patient_id = db.Column(db.Integer, db.ForeignKey('patient.id'), nullable=False)
    tooth_number = db.Column(db.String(5), nullable=False)
    status = db.Column(db.String(50))
    notes = db.Column(db.Text)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    clinic_id = db.Column(db.Integer, db.ForeignKey('clinic.id'), nullable=False)
    patient_id = db.Column(db.Integer, db.ForeignKey('patient.id'), nullable=False)
    treatment_id = db.Column(db.Integer, db.ForeignKey('treatment.id'))
    description = db.Column(db.String(200), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    due_date = db.Column(db.Date)
    paid_date = db.Column(db.Date)
    method = db.Column(db.String(30))
    status = db.Column(db.String(20), default='Pendente')
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ─── Helpers ──────────────────────────────────────────────────────────────────

@app.before_request
def load_logged_in_user():
    user_id = session.get('user_id')
    if user_id:
        g.user = User.query.get(user_id)
        g.clinic_id = g.user.clinic_id if g.user else None
    else:
        g.user = None
        g.clinic_id = None


def get_clinic_id():
    """Get clinic_id from session or query param (for admin access)"""
    if g.user and g.user.clinic_id:
        return g.user.clinic_id
    clinic_id = request.args.get('clinic_id', type=int)
    if clinic_id and g.user and g.user.is_admin:
        return clinic_id
    return g.clinic_id


def require_login(f):
    def wrapper(*args, **kwargs):
        if not g.user:
            flash('Faça login para continuar', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    wrapper.__name__ = f.__name__
    return wrapper


def require_admin(f):
    def wrapper(*args, **kwargs):
        if not g.user or not g.user.is_admin:
            flash('Acesso restrito', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    wrapper.__name__ = f.__name__
    return wrapper


# ─── Auth ─────────────────────────────────────────────────────────────────────

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = User.query.filter_by(email=email).first()

        if user and user.check_password(password) and user.active:
            session['user_id'] = user.id
            flash(f'Bem-vindo, {user.name}!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Email ou senha inválidos', 'danger')

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.pop('user_id', None)
    flash('Desconectado com sucesso', 'info')
    return redirect(url_for('login'))


@app.route('/signup/<token>', methods=['GET', 'POST'])
def signup(token):
    """Criar primeiro usuário da clínica via token convite"""
    clinic = Clinic.query.filter_by(invite_token=token).first()
    if not clinic:
        flash('Link de convite inválido', 'danger')
        return redirect(url_for('login'))

    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        name = request.form.get('name')

        if User.query.filter_by(email=email).first():
            flash('Email já cadastrado', 'danger')
        else:
            user = User(clinic_id=clinic.id, email=email, name=name, role='owner')
            user.set_password(password)
            clinic.invite_token = None
            db.session.add(user)
            db.session.commit()
            flash('Conta criada! Faça login para começar', 'success')
            return redirect(url_for('login'))

    return render_template('signup.html', clinic=clinic)


# ─── Admin Panel ───────────────────────────────────────────────────────────────

@app.route('/admin')
@require_admin
def admin_dashboard():
    """Painel do proprietário (você)"""
    total_clinics = Clinic.query.count()
    active_clinics = Clinic.query.filter_by(status='active').count()
    total_revenue = db.session.query(func.sum(Payment.amount)).filter_by(status='Pago').scalar() or 0
    pending_revenue = db.session.query(func.sum(Payment.amount)).filter_by(status='Pendente').scalar() or 0

    clinics = Clinic.query.order_by(Clinic.created_at.desc()).all()
    clinic_stats = []
    for clinic in clinics:
        stats = {
            'clinic': clinic,
            'patients': Patient.query.filter_by(clinic_id=clinic.id).count(),
            'appointments': Appointment.query.filter(Appointment.clinic_id==clinic.id, Appointment.date>=date.today()).count(),
            'revenue': db.session.query(func.sum(Payment.amount)).filter(Payment.clinic_id==clinic.id, Payment.status=='Pago').scalar() or 0,
        }
        clinic_stats.append(stats)

    return render_template('admin/dashboard.html',
        total_clinics=total_clinics,
        active_clinics=active_clinics,
        total_revenue=total_revenue,
        pending_revenue=pending_revenue,
        clinic_stats=clinic_stats)


@app.route('/admin/clinics/new', methods=['POST'])
@require_admin
def admin_clinic_new():
    """Criar nova clínica e gerar token convite"""
    name = request.form.get('name')
    cnpj = request.form.get('cnpj')
    admin_email = request.form.get('admin_email')

    clinic = Clinic(name=name, cnpj=cnpj, admin_email=admin_email)
    clinic.invite_token = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(32))
    db.session.add(clinic)
    db.session.commit()

    invite_url = url_for('signup', token=clinic.invite_token, _external=True)
    flash(f'Clínica criada! Link de convite: {invite_url}', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/clinics/<int:clinic_id>/access')
@require_admin
def admin_access_clinic(clinic_id):
    """Admin acessa clínica como super-user"""
    clinic = Clinic.query.get_or_404(clinic_id)
    session['user_id'] = None  # Não usar user_id
    session['admin_clinic_id'] = clinic_id
    flash(f'Acessando {clinic.name} como admin', 'info')
    return redirect(url_for('dashboard'))


# ─── Dashboard ─────────────────────────────────────────────────────────────────

@app.route('/')
@require_login
def dashboard():
    clinic_id = get_clinic_id()
    if not clinic_id:
        flash('Acesso restrito', 'danger')
        return redirect(url_for('login'))

    today = date.today()

    total_patients = Patient.query.filter_by(clinic_id=clinic_id).count()
    today_appointments = Appointment.query.filter(Appointment.clinic_id==clinic_id, Appointment.date==today).count()
    active_treatments = Treatment.query.filter(Treatment.clinic_id==clinic_id, Treatment.status=='Em andamento').count()
    pending_payments = db.session.query(func.sum(Payment.amount)).filter(Payment.clinic_id==clinic_id, Payment.status=='Pendente').scalar() or 0
    monthly_revenue = db.session.query(func.sum(Payment.amount)).filter(
        Payment.clinic_id==clinic_id,
        Payment.status=='Pago',
        Payment.paid_date>=date(today.year, today.month, 1)
    ).scalar() or 0

    upcoming = Appointment.query.filter(
        Appointment.clinic_id==clinic_id,
        Appointment.date>=today,
        Appointment.status.in_(['Agendado', 'Confirmado'])
    ).order_by(Appointment.date, Appointment.time).limit(5).all()

    recent_patients = Patient.query.filter_by(clinic_id=clinic_id).order_by(Patient.created_at.desc()).limit(5).all()

    chart_labels = []
    chart_data = []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        count = Appointment.query.filter(Appointment.clinic_id==clinic_id, Appointment.date==d).count()
        chart_labels.append(d.strftime('%d/%m'))
        chart_data.append(count)

    return render_template('dashboard.html',
        total_patients=total_patients,
        today_appointments=today_appointments,
        active_treatments=active_treatments,
        pending_payments=pending_payments,
        monthly_revenue=monthly_revenue,
        upcoming=upcoming,
        recent_patients=recent_patients,
        chart_labels=chart_labels,
        chart_data=chart_data,
        today=today,
        clinic_id=clinic_id)


# ─── Patients ──────────────────────────────────────────────────────────────────

@app.route('/patients')
@require_login
def patients():
    clinic_id = get_clinic_id()
    q = request.args.get('q', '')
    query = Patient.query.filter_by(clinic_id=clinic_id)
    if q:
        query = query.filter(Patient.name.ilike(f'%{q}%') | Patient.cpf.ilike(f'%{q}%'))
    patients_list = query.order_by(Patient.name).all()
    return render_template('patients/list.html', patients=patients_list, q=q)


@app.route('/patients/new', methods=['GET', 'POST'])
@require_login
def patient_new():
    clinic_id = get_clinic_id()
    if request.method == 'POST':
        bd = request.form.get('birth_date')
        patient = Patient(
            clinic_id=clinic_id,
            name=request.form['name'],
            cpf=request.form.get('cpf'),
            birth_date=datetime.strptime(bd, '%Y-%m-%d').date() if bd else None,
            phone=request.form.get('phone'),
            email=request.form.get('email'),
            address=request.form.get('address'),
            bruxism='bruxism' in request.form,
            allergies=request.form.get('allergies'),
            notes=request.form.get('notes'),
        )
        db.session.add(patient)
        db.session.commit()
        flash('Paciente cadastrado!', 'success')
        return redirect(url_for('patient_detail', id=patient.id))
    return render_template('patients/form.html', patient=None)


@app.route('/patients/<int:id>')
@require_login
def patient_detail(id):
    clinic_id = get_clinic_id()
    patient = Patient.query.get_or_404(id)
    if patient.clinic_id != clinic_id:
        flash('Acesso negado', 'danger')
        return redirect(url_for('patients'))

    appointments = Appointment.query.filter_by(patient_id=id).order_by(Appointment.date.desc()).all()
    treatments = Treatment.query.filter_by(patient_id=id).order_by(Treatment.created_at.desc()).all()
    payments = Payment.query.filter_by(patient_id=id).order_by(Payment.due_date.desc()).all()
    teeth = Tooth.query.filter_by(patient_id=id).all()
    total_paid = sum(p.amount for p in payments if p.status == 'Pago')
    total_pending = sum(p.amount for p in payments if p.status == 'Pendente')
    return render_template('patients/detail.html', patient=patient,
        appointments=appointments, treatments=treatments, payments=payments, teeth=teeth,
        total_paid=total_paid, total_pending=total_pending,
        dentists=Dentist.query.filter_by(clinic_id=clinic_id, active=True).all())


@app.route('/patients/<int:id>/edit', methods=['GET', 'POST'])
@require_login
def patient_edit(id):
    clinic_id = get_clinic_id()
    patient = Patient.query.get_or_404(id)
    if patient.clinic_id != clinic_id:
        flash('Acesso negado', 'danger')
        return redirect(url_for('patients'))

    if request.method == 'POST':
        bd = request.form.get('birth_date')
        patient.name = request.form['name']
        patient.cpf = request.form.get('cpf')
        patient.birth_date = datetime.strptime(bd, '%Y-%m-%d').date() if bd else None
        patient.phone = request.form.get('phone')
        patient.email = request.form.get('email')
        patient.address = request.form.get('address')
        patient.bruxism = 'bruxism' in request.form
        patient.allergies = request.form.get('allergies')
        patient.notes = request.form.get('notes')
        db.session.commit()
        flash('Paciente atualizado!', 'success')
        return redirect(url_for('patient_detail', id=id))
    return render_template('patients/form.html', patient=patient)


@app.route('/patients/<int:id>/delete', methods=['POST'])
@require_login
def patient_delete(id):
    clinic_id = get_clinic_id()
    patient = Patient.query.get_or_404(id)
    if patient.clinic_id != clinic_id:
        flash('Acesso negado', 'danger')
        return redirect(url_for('patients'))
    db.session.delete(patient)
    db.session.commit()
    flash('Paciente removido.', 'info')
    return redirect(url_for('patients'))


# ─── Other Routes (simplified - to be continued) ───────────────────────────────

@app.route('/appointments')
@require_login
def appointments():
    clinic_id = get_clinic_id()
    today = date.today()
    filter_date = request.args.get('date', today.strftime('%Y-%m-%d'))
    query = Appointment.query.filter_by(clinic_id=clinic_id)
    if filter_date:
        try:
            fd = datetime.strptime(filter_date, '%Y-%m-%d').date()
            query = query.filter_by(date=fd)
        except ValueError:
            pass
    appts = query.order_by(Appointment.time).all()
    return render_template('appointments/list.html', appointments=appts,
        filter_date=filter_date,
        patients=Patient.query.filter_by(clinic_id=clinic_id).all(),
        dentists=Dentist.query.filter_by(clinic_id=clinic_id, active=True).all())


@app.route('/treatments')
@require_login
def treatments():
    clinic_id = get_clinic_id()
    treatments_list = Treatment.query.filter_by(clinic_id=clinic_id).order_by(Treatment.created_at.desc()).all()
    return render_template('treatments/list.html', treatments=treatments_list,
        patients=Patient.query.filter_by(clinic_id=clinic_id).all(),
        dentists=Dentist.query.filter_by(clinic_id=clinic_id, active=True).all())


@app.route('/financial')
@require_login
def financial():
    clinic_id = get_clinic_id()
    today = date.today()
    payments = Payment.query.filter_by(clinic_id=clinic_id).order_by(Payment.due_date.desc()).all()
    total_paid = sum(p.amount for p in payments if p.status == 'Pago')
    total_pending = sum(p.amount for p in payments if p.status == 'Pendente')
    return render_template('financial/list.html', payments=payments,
        total_paid=total_paid, total_pending=total_pending,
        patients=Patient.query.filter_by(clinic_id=clinic_id).all(),
        today=today)


@app.route('/dentists')
@require_login
def dentists():
    clinic_id = get_clinic_id()
    dentists_list = Dentist.query.filter_by(clinic_id=clinic_id).order_by(Dentist.name).all()
    return render_template('dentists/list.html', dentists=dentists_list)


@app.route('/calendar')
@require_login
def calendar():
    return render_template('calendar.html')


@app.route('/api/appointments')
@require_login
def api_appointments():
    clinic_id = get_clinic_id()
    events = []
    for a in Appointment.query.filter_by(clinic_id=clinic_id).all():
        color_map = {
            'Agendado': '#3b82f6',
            'Confirmado': '#10b981',
            'Realizado': '#6b7280',
            'Cancelado': '#ef4444',
        }
        events.append({
            'id': a.id,
            'title': f"{a.time.strftime('%H:%M')} - {a.patient.name}",
            'start': f"{a.date.isoformat()}T{a.time.strftime('%H:%M')}:00",
            'color': color_map.get(a.status, '#3b82f6'),
            'url': url_for('patient_detail', id=a.patient_id),
        })
    return jsonify(events)


# ─── Appointments (CRUD) ──────────────────────────────────────────────────────

@app.route('/appointments/new', methods=['GET', 'POST'])
@require_login
def appointment_new():
    clinic_id = get_clinic_id()
    if request.method == 'POST':
        try:
            date_str = request.form.get('date')
            time_str = request.form.get('time')
            appointment = Appointment(
                clinic_id=clinic_id,
                patient_id=request.form['patient_id'],
                dentist_id=request.form.get('dentist_id'),
                date=datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else None,
                time=datetime.strptime(time_str, '%H:%M').time() if time_str else None,
                type=request.form.get('type'),
                status='Agendado'
            )
            db.session.add(appointment)
            db.session.commit()
            flash('Consulta agendada!', 'success')
            return redirect(url_for('appointments'))
        except Exception as e:
            flash(f'Erro ao agendar: {str(e)}', 'danger')
    return render_template('appointments/form.html', appointment=None,
                         patients=Patient.query.filter_by(clinic_id=clinic_id).all(),
                         dentists=Dentist.query.filter_by(clinic_id=clinic_id, active=True).all())


@app.route('/appointments/<int:id>/edit', methods=['POST'])
@require_login
def appointment_edit(id):
    clinic_id = get_clinic_id()
    apt = Appointment.query.get_or_404(id)
    if apt.clinic_id != clinic_id:
        flash('Acesso negado', 'danger')
        return redirect(url_for('appointments'))
    apt.status = request.form.get('status', apt.status)
    db.session.commit()
    flash('Consulta atualizada!', 'success')
    return redirect(url_for('appointments'))


@app.route('/appointments/<int:id>/delete', methods=['POST'])
@require_login
def appointment_delete(id):
    clinic_id = get_clinic_id()
    apt = Appointment.query.get_or_404(id)
    if apt.clinic_id != clinic_id:
        flash('Acesso negado', 'danger')
        return redirect(url_for('appointments'))
    db.session.delete(apt)
    db.session.commit()
    flash('Consulta removida.', 'info')
    return redirect(url_for('appointments'))


# ─── Dentists (CRUD) ──────────────────────────────────────────────────────────

@app.route('/dentists/new', methods=['GET', 'POST'])
@require_login
def dentist_new():
    clinic_id = get_clinic_id()
    if request.method == 'POST':
        dentist = Dentist(
            clinic_id=clinic_id,
            name=request.form['name'],
            cro=request.form.get('cro'),
            specialties=request.form.get('specialties'),
            phone=request.form.get('phone'),
            email=request.form.get('email'),
            active=True
        )
        db.session.add(dentist)
        db.session.commit()
        flash('Dentista cadastrado!', 'success')
        return redirect(url_for('dentists'))
    return render_template('dentists/form.html', dentist=None)


@app.route('/dentists/<int:id>/edit', methods=['GET', 'POST'])
@require_login
def dentist_edit(id):
    clinic_id = get_clinic_id()
    dentist = Dentist.query.get_or_404(id)
    if dentist.clinic_id != clinic_id:
        flash('Acesso negado', 'danger')
        return redirect(url_for('dentists'))
    if request.method == 'POST':
        dentist.name = request.form['name']
        dentist.cro = request.form.get('cro')
        dentist.specialties = request.form.get('specialties')
        dentist.phone = request.form.get('phone')
        dentist.email = request.form.get('email')
        db.session.commit()
        flash('Dentista atualizado!', 'success')
        return redirect(url_for('dentists'))
    return render_template('dentists/form.html', dentist=dentist)


@app.route('/dentists/<int:id>/delete', methods=['POST'])
@require_login
def dentist_delete(id):
    clinic_id = get_clinic_id()
    dentist = Dentist.query.get_or_404(id)
    if dentist.clinic_id != clinic_id:
        flash('Acesso negado', 'danger')
        return redirect(url_for('dentists'))
    db.session.delete(dentist)
    db.session.commit()
    flash('Dentista removido.', 'info')
    return redirect(url_for('dentists'))


# ─── Treatments ───────────────────────────────────────────────────────────────

@app.route('/treatments/<int:id>/update', methods=['POST'])
@require_login
def treatment_update(id):
    clinic_id = get_clinic_id()
    treatment = Treatment.query.get_or_404(id)
    if treatment.clinic_id != clinic_id:
        flash('Acesso negado', 'danger')
        return redirect(url_for('treatments'))
    treatment.status = request.form.get('status', treatment.status)
    treatment.sessions_completed = int(request.form.get('sessions_completed', treatment.sessions_completed))
    treatment.paid_amount = float(request.form.get('paid_amount', treatment.paid_amount or 0))
    end_date_str = request.form.get('end_date')
    if end_date_str:
        treatment.end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
    db.session.commit()
    flash('Tratamento atualizado!', 'success')
    return redirect(url_for('treatments'))


@app.route('/treatments/<int:id>/delete', methods=['POST'])
@require_login
def treatment_delete(id):
    clinic_id = get_clinic_id()
    treatment = Treatment.query.get_or_404(id)
    if treatment.clinic_id != clinic_id:
        flash('Acesso negado', 'danger')
        return redirect(url_for('treatments'))
    db.session.delete(treatment)
    db.session.commit()
    flash('Tratamento removido.', 'info')
    return redirect(url_for('treatments'))


# ─── Financial ────────────────────────────────────────────────────────────────

@app.route('/financial')
# ─── Init ──────────────────────────────────────────────────────────────────────

def create_sample_data():
    if User.query.filter_by(role='admin').first():
        return

    # Criar admin (você)
    admin = User(email=ADMIN_EMAIL, name='Admin', role='admin')
    admin.set_password('admin123')
    db.session.add(admin)
    db.session.flush()

    # Criar clínica demo
    clinic = Clinic(name='Clínica Demo', cnpj='00.000.000/0000-00', admin_email='demo@odonto.com')
    db.session.add(clinic)
    db.session.flush()

    # Criar usuário owner da clínica
    owner = User(clinic_id=clinic.id, email='owner@demo.com', name='Dra. Ana Silva', role='owner')
    owner.set_password('demo123')
    db.session.add(owner)
    db.session.flush()

    # Criar dentista
    dentist = Dentist(clinic_id=clinic.id, name='Dra. Ana Silva', cro='CRO-12345')
    db.session.add(dentist)
    db.session.flush()

    # Criar paciente
    p1 = Patient(clinic_id=clinic.id, name='Maria Oliveira', phone='(11) 99111-2222', bruxism=True)
    db.session.add(p1)
    db.session.flush()

    # Criar consulta
    today = date.today()
    a1 = Appointment(clinic_id=clinic.id, patient_id=p1.id, dentist_id=dentist.id, date=today,
                    time=datetime.strptime('09:00', '%H:%M').time(), type='Limpeza', status='Confirmado')
    db.session.add(a1)
    db.session.commit()


with app.app_context():
    db.create_all()
    create_sample_data()

if __name__ == '__main__':
    app.run(debug=True, port=5000)
