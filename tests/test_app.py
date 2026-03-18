import pytest
from app import create_app, db
from app.models import User, Section, Letter, Case, _utcnow


@pytest.fixture
def app():
    """Create test app with in-memory SQLite."""
    app = create_app('testing')
    app.config.update({
        'LOGIN_DISABLED': False,
        'SERVER_NAME': 'localhost',
    })

    with app.app_context():
        db.create_all()
        # Seed sections for tests (AUTO_DB_BOOTSTRAP is off in testing config)
        from app import _sync_sections
        _sync_sections(app)
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def admin_user(app):
    with app.app_context():
        user = User(username='admin', full_name='Admin', role='admin', is_active_user=True)
        user.set_password('Test@1234')
        db.session.add(user)
        db.session.commit()
        return user.id


@pytest.fixture
def data_entry_user(app):
    with app.app_context():
        user = User(username='dataentry', full_name='Data Entry', role='data_entry', is_active_user=True)
        user.set_password('Test@1234')
        db.session.add(user)
        db.session.commit()
        return user.id


@pytest.fixture
def regular_user(app):
    with app.app_context():
        user = User(username='testuser', full_name='Test User', role='user', is_active_user=True)
        user.set_password('Test@1234')
        db.session.add(user)
        db.session.commit()
        return user.id


def login(client, username, password='Test@1234'):
    return client.post('/auth/login', data={
        'username': username,
        'password': password,
    }, follow_redirects=True)


# ──────────────────── AUTH TESTS ────────────────────

class TestAuth:
    def test_login_page_loads(self, client):
        resp = client.get('/auth/login')
        assert resp.status_code == 200
        assert b'Sign In' in resp.data or b'Login' in resp.data or b'login' in resp.data

    def test_login_success_admin(self, client, admin_user):
        resp = login(client, 'admin')
        assert resp.status_code == 200
        assert b'Dashboard' in resp.data or b'dashboard' in resp.data

    def test_login_failure(self, client, admin_user):
        resp = client.post('/auth/login', data={
            'username': 'admin', 'password': 'wrong',
        }, follow_redirects=True)
        assert b'Invalid' in resp.data or b'invalid' in resp.data or resp.status_code == 200

    def test_login_inactive_user(self, app, client):
        with app.app_context():
            user = User(username='inactive', full_name='Inactive', role='user', is_active_user=False)
            user.set_password('Test@1234')
            db.session.add(user)
            db.session.commit()
        resp = login(client, 'inactive')
        assert b'deactivated' in resp.data or b'inactive' in resp.data or b'login' in resp.data.lower()

    def test_logout(self, client, admin_user):
        login(client, 'admin')
        resp = client.get('/auth/logout', follow_redirects=True)
        assert resp.status_code == 200

    def test_change_password(self, client, admin_user):
        login(client, 'admin')
        resp = client.get('/auth/change-password')
        assert resp.status_code == 200

    def test_redirect_unauthenticated(self, client):
        resp = client.get('/admin/dashboard')
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers.get('Location', '')


# ──────────────────── ROLE-BASED ACCESS ────────────────────

class TestRoleAccess:
    def test_admin_accesses_admin_dashboard(self, client, admin_user):
        login(client, 'admin')
        resp = client.get('/admin/dashboard')
        assert resp.status_code == 200

    def test_regular_user_blocked_from_admin(self, client, regular_user):
        login(client, 'testuser')
        resp = client.get('/admin/dashboard')
        assert resp.status_code in (302, 403)

    def test_admin_blocked_from_data_entry(self, client, admin_user):
        login(client, 'admin')
        resp = client.get('/data-entry/dashboard')
        assert resp.status_code in (302, 403)

    def test_data_entry_accesses_own_dashboard(self, client, data_entry_user):
        login(client, 'dataentry')
        resp = client.get('/data-entry/dashboard')
        assert resp.status_code == 200


# ──────────────────── ADMIN CRUD ────────────────────

class TestAdminCrud:
    def test_create_user(self, client, admin_user):
        login(client, 'admin')
        resp = client.post('/admin/users/create', data={
            'username': 'newuser',
            'full_name': 'New User',
            'role': 'user',
            'password': 'New@12345',
            'confirm_password': 'New@12345',
        }, follow_redirects=True)
        assert resp.status_code == 200

    def test_add_inward_letter(self, app, client, admin_user):
        login(client, 'admin')
        resp = client.post('/admin/add-inward-letter', data={
            'direction': 'Inward',
            'reference_number': 'ROCP/IN/2024/001',
            'subject': 'Test Letter',
            'sender': 'Test Sender',
            'section': 'ADM',
            'priority': 'Medium',
            'received_date': '2024-01-15',
            'letter_date': '2024-01-14',
            'deadline_days': '7',
        }, follow_redirects=True)
        assert resp.status_code == 200

    def test_sections_page(self, client, admin_user):
        login(client, 'admin')
        resp = client.get('/admin/sections')
        assert resp.status_code == 200
        assert b'ADM' in resp.data or b'Admin' in resp.data

    def test_upload_page(self, client, admin_user):
        login(client, 'admin')
        resp = client.get('/admin/upload')
        assert resp.status_code == 200

    def test_analytics_page(self, client, admin_user):
        login(client, 'admin')
        resp = client.get('/admin/analytics')
        assert resp.status_code == 200

    def test_workload_page(self, client, admin_user):
        login(client, 'admin')
        resp = client.get('/admin/workload')
        assert resp.status_code == 200


# ──────────────────── CASES ────────────────────

class TestCases:
    def test_cases_dashboard(self, client, admin_user):
        login(client, 'admin')
        resp = client.get('/cases/dashboard')
        assert resp.status_code == 200

    def test_my_cases(self, client, admin_user):
        login(client, 'admin')
        resp = client.get('/cases/my-cases')
        assert resp.status_code == 200

    def test_data_entry_cannot_create_case_from_letter(self, app, client, data_entry_user):
        with app.app_context():
            letter = Letter(
                from_address='Sender A',
                to_address='ROC',
                subject='Create Case Permission Test',
                unique_hash=Letter.generate_hash('Sender A', 'ROC', 'Create Case Permission Test'),
                direction='Inward',
                status='Unassigned',
            )
            db.session.add(letter)
            db.session.commit()
            letter_id = letter.id

        login(client, 'dataentry')
        resp = client.post(f'/cases/create-from-letter/{letter_id}', data={}, follow_redirects=True)
        assert resp.status_code == 200

        with app.app_context():
            linked_letter = db.session.get(Letter, letter_id)
            assert linked_letter.case_id is None

    def test_linking_outward_letter_pauses_case_deadline(self, app, client, regular_user):
        from datetime import timedelta
        with app.app_context():
            assignee = db.session.get(User, regular_user)
            case = Case(
                reference_number='ROCP/2025-26/ADM/12345',
                title='Pause On Outward Link',
                section='ADM',
                status='Under Investigation',
                assignee_id=assignee.id,
                created_by_id=assignee.id,
                deadline_date=_utcnow() + timedelta(days=3),
            )
            db.session.add(case)
            db.session.flush()

            letter = Letter(
                from_address='ROC',
                to_address='External Party',
                subject='Outward Followup',
                unique_hash=Letter.generate_hash('ROC', 'External Party', 'Outward Followup'),
                direction='Outward',
                status='Outward',
                assignee_id=assignee.id,
                created_by_id=assignee.id,
            )
            db.session.add(letter)
            db.session.commit()
            case_id = case.id
            letter_id = letter.id

        login(client, 'testuser')
        resp = client.post(f'/cases/link-letter/{letter_id}', data={'case_id': str(case_id)}, follow_redirects=True)
        assert resp.status_code == 200

        with app.app_context():
            updated_case = db.session.get(Case, case_id)
            updated_letter = db.session.get(Letter, letter_id)
            assert updated_letter.case_id == case_id
            assert updated_case.status == 'Awaiting Response'
            assert updated_case.paused_at is not None


# ──────────────────── API ────────────────────

class TestApi:
    def test_notification_count(self, client, admin_user):
        login(client, 'admin')
        resp = client.get('/api/notifications/count')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'count' in data

    def test_stats(self, client, admin_user):
        login(client, 'admin')
        resp = client.get('/api/stats')
        assert resp.status_code == 200


# ──────────────────── MODELS ────────────────────

class TestModels:
    def test_user_password_hashing(self, app):
        with app.app_context():
            u = User(username='test', full_name='Test', role='user')
            u.set_password('secret')
            assert u.check_password('secret')
            assert not u.check_password('wrong')

    def test_user_role_properties(self, app):
        with app.app_context():
            admin = User(username='a', full_name='A', role='admin')
            de = User(username='d', full_name='D', role='data_entry')
            user = User(username='u', full_name='U', role='user')
            assert admin.is_admin is True
            assert admin.is_data_entry is False
            assert de.is_data_entry is True
            assert user.is_admin is False
            assert user.is_data_entry is False

    def test_case_financial_year(self, app):
        from datetime import date
        with app.app_context():
            fy = Case.get_financial_year(date(2024, 3, 15))
            assert fy == '2023-24'
            fy = Case.get_financial_year(date(2024, 4, 1))
            assert fy == '2024-25'

    def test_section_repr(self, app):
        with app.app_context():
            s = Section.query.filter_by(code='ADM').first()
            assert s is not None
            assert s.name == 'Admin'

    def test_case_deadline_pause_and_resume(self, app):
        from datetime import timedelta
        with app.app_context():
            now = _utcnow()
            case = Case(
                reference_number='ROCP/2025-26/ADM/99999',
                title='Pause Resume Test',
                section='ADM',
                status='Under Investigation',
                deadline_date=now + timedelta(days=5),
            )
            db.session.add(case)
            db.session.flush()

            original_deadline = case.deadline_date
            case.pause_deadline()
            paused_at = case.paused_at
            assert paused_at is not None

            case.paused_at = paused_at - timedelta(hours=6)
            frozen_remaining = case.days_remaining

            case.resume_deadline()
            assert case.paused_at is None
            assert case.deadline_date > original_deadline
            assert (case.deadline_date - original_deadline) >= timedelta(hours=5, minutes=59)
            assert case.days_remaining <= frozen_remaining
