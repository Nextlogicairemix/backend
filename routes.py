from flask import Blueprint, request, jsonify
from models import db, User, AccessCode, RemixHistory, CourseProgress, ToolPermission, AVAILABLE_TOOLS
from flask_login import login_user, logout_user, current_user, login_required
from datetime import datetime, timedelta
import secrets
import requests
import os

bp = Blueprint('api', __name__)

PREMIUM_TOOLS = ['email', 'ad', 'blog', 'story', 'smalltalk', 'salespitch', 
                 'thanks', 'followup', 'apology', 'reminder', 'agenda', 'interview']

# ============================================
# USER MANAGEMENT
# ============================================

@bp.route('/api/register', methods=['POST'])
def register_user():
    data = request.json
    
    # Check if access code is provided (school user)
    access_code = data.get('access_code')
    if access_code:
        code = AccessCode.query.filter_by(code=access_code, active=True).first()
        if not code:
            return jsonify({'error': 'Invalid access code'}), 400
    
    # Check if email exists
    if User.query.filter_by(email=data['email']).first():
        return jsonify({'error': 'Email already registered'}), 400
    
    # Create user
    user = User(
        name=data.get('name'),
        email=data['email'],
        access_code=access_code,
        role='student',
        school=code.school_name if access_code and code else None
    )
    user.set_password(data['password'])
    
    db.session.add(user)
    db.session.commit()
    
    return jsonify({
        'message': 'Registered successfully',
        'is_school_user': user.is_school_user()
    }), 201


@bp.route('/api/login', methods=['POST'])
def login():
    data = request.json
    user = User.query.filter_by(email=data['email']).first()
    
    if user and user.check_password(data['password']):
        login_user(user)
        return jsonify({
            'message': 'Login successful',
            'user': {
                'id': user.id,
                'name': user.name,
                'email': user.email,
                'role': user.role,
                'course_completed': user.course_completed,
                'is_school_user': user.is_school_user(),
                'is_premium': user.can_use_premium_features(),
                'allowed_tools': user.get_allowed_tools()
            }
        }), 200
    
    return jsonify({'error': 'Invalid credentials'}), 401


@bp.route('/api/logout')
@login_required
def logout():
    logout_user()
    return jsonify({'message': 'Logged out'})


@bp.route('/api/check_session')
def check_session():
    if current_user.is_authenticated:
        return jsonify({
            'logged_in': True,
            'user': {
                'id': current_user.id,
                'name': current_user.name,
                'role': current_user.role,
                'course_completed': current_user.course_completed,
                'is_school_user': current_user.is_school_user(),
                'is_premium': current_user.can_use_premium_features(),
                'allowed_tools': current_user.get_allowed_tools()
            }
        })
    return jsonify({'logged_in': False})


# ============================================
# TOOL PERMISSIONS (STUDENT VIEW)
# ============================================

@bp.route('/api/tools/available', methods=['GET'])
@login_required
def get_available_tools():
    """Get list of tools this student can access"""
    allowed_tool_ids = current_user.get_allowed_tools()
    
    # Filter tools based on permissions
    if allowed_tool_ids is None:
        # Non-school user - show all tools but mark premium ones
        tools = AVAILABLE_TOOLS
    else:
        # School user - only show enabled tools
        tools = [t for t in AVAILABLE_TOOLS if t['id'] in allowed_tool_ids]
    
    # Add access status to each tool
    result = []
    for tool in tools:
        can_access = True
        reason = None
        
        # Check course completion for school users
        if current_user.is_school_user() and not current_user.course_completed:
            can_access = False
            reason = 'Complete course first'
        
        # Check premium for non-school users
        elif not current_user.is_school_user() and tool['premium']:
            if not current_user.can_use_premium_features():
                can_access = False
                reason = 'Premium required'
        
        result.append({
            **tool,
            'can_access': can_access,
            'reason': reason
        })
    
    return jsonify({'tools': result})


# ============================================
# COURSE MANAGEMENT
# ============================================

@bp.route('/api/course/progress', methods=['GET'])
@login_required
def get_course_progress():
    """Get student's progress through all 4 modules"""
    progress = CourseProgress.query.filter_by(user_id=current_user.id).all()
    modules = {}
    for p in progress:
        modules[p.module_number] = {
            'completed': p.completed,
            'completed_at': p.completed_at.isoformat() if p.completed_at else None
        }
    
    # Fill in missing modules
    for i in range(1, 5):
        if i not in modules:
            modules[i] = {'completed': False, 'completed_at': None}
    
    all_complete = all(modules[i]['completed'] for i in range(1, 5))
    
    return jsonify({
        'modules': modules,
        'course_completed': all_complete
    })


@bp.route('/api/course/complete_module', methods=['POST'])
@login_required
def complete_module():
    """Mark a single module as complete"""
    data = request.json
    module_num = data.get('module_number')
    
    if not module_num or module_num not in [1, 2, 3, 4]:
        return jsonify({'error': 'Invalid module number'}), 400
    
    # Check if already exists
    progress = CourseProgress.query.filter_by(
        user_id=current_user.id, 
        module_number=module_num
    ).first()
    
    if not progress:
        progress = CourseProgress(
            user_id=current_user.id,
            module_number=module_num
        )
        db.session.add(progress)
    
    progress.completed = True
    progress.completed_at = datetime.utcnow()
    
    # Check if all modules are complete
    all_modules = CourseProgress.query.filter_by(user_id=current_user.id).all()
    if len(all_modules) == 4 and all(m.completed for m in all_modules):
        current_user.course_completed = True
    
    db.session.commit()
    
    return jsonify({
        'message': f'Module {module_num} completed',
        'course_completed': current_user.course_completed
    })


# ============================================
# AI REMIX / TOOL USAGE
# ============================================

@bp.route('/api/remix', methods=['POST'])
@login_required
def remix_content():
    data = request.json
    content = data.get('content', '').strip()
    tool_type = data.get('style', 'tweet')
    
    if not content:
        return jsonify({'error': 'No content provided'}), 400
    
    # Check if course completed (for school users)
    if current_user.is_school_user() and not current_user.course_completed:
        return jsonify({'error': 'Please complete the course before using tools'}), 403
    
    # Check if tool is allowed for this student
    allowed_tools = current_user.get_allowed_tools()
    if allowed_tools is not None and tool_type not in allowed_tools:
        return jsonify({'error': 'Tool not available. Contact your teacher.'}), 403
    
    # Check if premium tool and user has access (for non-school users)
    if not current_user.is_school_user() and tool_type in PREMIUM_TOOLS:
        if not current_user.can_use_premium_features():
            return jsonify({
                'error': 'Premium feature required',
                'requiresPremium': True
            }), 403
    
    # Call AI API (Gemini)
    try:
        api_key = os.environ.get('GEMINI_API_KEY')
        if not api_key:
            return jsonify({'error': 'AI service not configured'}), 500
        
        prompts = {
            'tweet': f'Convert this into an engaging Twitter thread with 3-5 tweets:\n\n{content}',
            'linkedin': f'Rewrite as a professional LinkedIn post:\n\n{content}',
            'email': f'Write a professional email based on:\n\n{content}',
            'blog': f'Expand into a blog post with headers:\n\n{content}',
            'summary': f'Summarize this in 2-3 sentences:\n\n{content}',
            'ad': f'Create compelling ad copy for:\n\n{content}',
            'story': f'Write a creative story based on:\n\n{content}',
        }
        
        prompt = prompts.get(tool_type, prompts['tweet'])
        
        response = requests.post(
            f'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent?key={api_key}',
            headers={'Content-Type': 'application/json'},
            json={
                'contents': [{'parts': [{'text': prompt}]}],
                'generationConfig': {'temperature': 0.7, 'maxOutputTokens': 2000}
            },
            timeout=120
        )
        
        if response.status_code == 200:
            result = response.json()
            output = result['candidates'][0]['content']['parts'][0]['text']
            
            # Save to history
            history = RemixHistory(
                user_id=current_user.id,
                tool_type=tool_type,
                input_text=content,
                output_text=output
            )
            db.session.add(history)
            db.session.commit()
            
            return jsonify({'output': output})
        else:
            return jsonify({'error': 'AI service error'}), 500
            
    except Exception as e:
        print(f"Remix error: {e}")
        return jsonify({'error': 'Failed to generate content'}), 500


# ============================================
# ADMIN / TEACHER ROUTES - TOOL MANAGEMENT
# ============================================

@bp.route('/api/admin/tools/available', methods=['GET'])
@login_required
def get_all_tools():
    """Get all available tools (for teacher to enable/disable)"""
    if current_user.role != 'admin':
        return jsonify({'error': 'Not authorized'}), 403
    
    return jsonify({'tools': AVAILABLE_TOOLS})


@bp.route('/api/admin/access_code/<code>/tools', methods=['GET'])
@login_required
def get_code_tools(code):
    """Get enabled tools for a specific access code"""
    if current_user.role != 'admin':
        return jsonify({'error': 'Not authorized'}), 403
    
    access_code = AccessCode.query.filter_by(code=code, created_by=current_user.id).first()
    if not access_code:
        return jsonify({'error': 'Access code not found'}), 404
    
    enabled_tools = ToolPermission.query.filter_by(access_code_id=access_code.id).all()
    enabled_tool_ids = [t.tool_type for t in enabled_tools if t.enabled]
    
    # Return all tools with enabled status
    tools_with_status = []
    for tool in AVAILABLE_TOOLS:
        tools_with_status.append({
            **tool,
            'enabled': tool['id'] in enabled_tool_ids
        })
    
    return jsonify({
        'access_code': code,
        'school_name': access_code.school_name,
        'tools': tools_with_status
    })


@bp.route('/api/admin/access_code/<code>/tools', methods=['POST'])
@login_required
def update_code_tools(code):
    """Enable/disable specific tools for an access code"""
    if current_user.role != 'admin':
        return jsonify({'error': 'Not authorized'}), 403
    
    access_code = AccessCode.query.filter_by(code=code, created_by=current_user.id).first()
    if not access_code:
        return jsonify({'error': 'Access code not found'}), 404
    
    data = request.json
    tool_type = data.get('tool_type')
    enabled = data.get('enabled', True)
    
    # Check if permission exists
    permission = ToolPermission.query.filter_by(
        access_code_id=access_code.id,
        tool_type=tool_type
    ).first()
    
    if not permission:
        permission = ToolPermission(
            access_code_id=access_code.id,
            tool_type=tool_type,
            enabled=enabled
        )
        db.session.add(permission)
    else:
        permission.enabled = enabled
    
    db.session.commit()
    
    return jsonify({
        'message': f'Tool {tool_type} {"enabled" if enabled else "disabled"}',
        'tool_type': tool_type,
        'enabled': enabled
    })


@bp.route('/api/admin/access_code/<code>/tools/bulk', methods=['POST'])
@login_required
def bulk_update_tools(code):
    """Enable/disable multiple tools at once"""
    if current_user.role != 'admin':
        return jsonify({'error': 'Not authorized'}), 403
    
    access_code = AccessCode.query.filter_by(code=code, created_by=current_user.id).first()
    if not access_code:
        return jsonify({'error': 'Access code not found'}), 404
    
    data = request.json
    enabled_tools = data.get('enabled_tools', [])  # List of tool IDs to enable
    
    # Disable all existing
    existing = ToolPermission.query.filter_by(access_code_id=access_code.id).all()
    for perm in existing:
        perm.enabled = False
    
    # Enable selected tools
    for tool_id in enabled_tools:
        permission = ToolPermission.query.filter_by(
            access_code_id=access_code.id,
            tool_type=tool_id
        ).first()
        
        if not permission:
            permission = ToolPermission(
                access_code_id=access_code.id,
                tool_type=tool_id,
                enabled=True
            )
            db.session.add(permission)
        else:
            permission.enabled = True
    
    db.session.commit()
    
    return jsonify({
        'message': f'{len(enabled_tools)} tools enabled',
        'enabled_tools': enabled_tools
    })


@bp.route('/api/admin/create_code', methods=['POST'])
@login_required
def create_code():
    if current_user.role != 'admin':
        return jsonify({'error': 'Not authorized'}), 403
    
    data = request.json
    school_name = data.get('school_name', 'Default School')
    default_tools = data.get('default_tools', ['tweet', 'summary'])  # Start with basic tools
    
    new_code = f"{secrets.token_hex(4).upper()}"
    code = AccessCode(
        code=new_code,
        created_by=current_user.id,
        school_name=school_name
    )
    db.session.add(code)
    db.session.flush()  # Get the ID
    
    # Add default tools
    for tool_id in default_tools:
        permission = ToolPermission(
            access_code_id=code.id,
            tool_type=tool_id,
            enabled=True
        )
        db.session.add(permission)
    
    db.session.commit()
    
    return jsonify({
        'code': new_code,
        'school_name': school_name,
        'default_tools': default_tools
    })


@bp.route('/api/admin/students', methods=['GET'])
@login_required
def get_students():
    """Get all students for a teacher's access codes"""
    if current_user.role != 'admin':
        return jsonify({'error': 'Not authorized'}), 403
    
    # Get all codes created by this teacher
    codes = AccessCode.query.filter_by(created_by=current_user.id).all()
    code_strings = [c.code for c in codes]
    
    # Get all students with those codes
    students = User.query.filter(User.access_code.in_(code_strings)).all()
    
    student_data = []
    for student in students:
        # Get their recent tool usage
        recent_tool = RemixHistory.query.filter_by(user_id=student.id)\
            .order_by(RemixHistory.created_at.desc()).first()
        
        student_data.append({
            'id': student.id,
            'name': student.name,
            'email': student.email,
            'course_completed': student.course_completed,
            'access_code': student.access_code,
            'current_tool': recent_tool.tool_type if recent_tool else None,
            'last_active': recent_tool.created_at.isoformat() if recent_tool else None
        })
    
    return jsonify({'students': student_data})


@bp.route('/api/admin/student/<int:student_id>/history', methods=['GET'])
@login_required
def get_student_history(student_id):
    """Get a student's tool usage history"""
    if current_user.role != 'admin':
        return jsonify({'error': 'Not authorized'}), 403
    
    student = User.query.get(student_id)
    if not student:
        return jsonify({'error': 'Student not found'}), 404
    
    history = RemixHistory.query.filter_by(user_id=student_id)\
        .order_by(RemixHistory.created_at.desc()).limit(50).all()
    
    history_data = [{
        'tool_type': h.tool_type,
        'created_at': h.created_at.isoformat(),
        'input_preview': h.input_text[:100] if h.input_text else ''
    } for h in history]
    
    return jsonify({
        'student_name': student.name,
        'history': history_data
    })


# ============================================
# PREMIUM SUBSCRIPTION
# ============================================

@bp.route('/api/update_subscription', methods=['POST'])
@login_required
def update_subscription():
    """Activate premium subscription (PayPal callback)"""
    data = request.json
    subscription_id = data.get('subscriptionID')
    
    # Set premium for 30 days
    current_user.is_premium = True
    current_user.premium_expires_at = datetime.utcnow() + timedelta(days=30)
    
    db.session.commit()
    
    return jsonify({
        'message': 'Premium activated',
        'expires_at': current_user.premium_expires_at.isoformat()
    })