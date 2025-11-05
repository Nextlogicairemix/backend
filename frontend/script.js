const API_BASE_URL = 'https://back-thbr.onrender.com';

function trackEvent(eventName, parameters = {}) {
    if (typeof gtag !== 'undefined') {
        gtag('event', eventName, parameters);
    }
}

function trackPageView(pageName) {
    trackEvent('page_view', {
        page_title: pageName,
        page_location: window.location.href
    });
}

function trackRegistration() {
    trackEvent('sign_up', {
        method: 'email'
    });
}

function trackLogin() {
    trackEvent('login', {
        method: 'email'
    });
}

function trackRemix(remixType, userTier) {
    trackEvent('remix_content', {
        content_type: remixType,
        user_tier: userTier
    });
}

function trackPaywallShown(trigger) {
    trackEvent('view_paywall', {
        trigger: trigger
    });
}

function trackSubscription(subscriptionID) {
    trackEvent('purchase', {
        transaction_id: subscriptionID,
        value: 4.99,
        currency: 'USD',
        items: [{
            item_id: 'premium_monthly',
            item_name: 'Premium Subscription',
            price: 4.99,
            quantity: 1
        }]
    });
}

function trackButtonClick(buttonName) {
    trackEvent('button_click', {
        button_name: buttonName
    });
}

function trackContactForm() {
    trackEvent('contact_form_submit', {
        form_name: 'main_contact'
    });
}

document.addEventListener('DOMContentLoaded', () => {
    // User state
    let userTier = 'guest'; // 'guest', 'free', 'premium'
    let guestUsesLeft = 3;
    let isLoggedIn = false;
    let isPaid = false;

    // Premium-only features
    const premiumOptions = [
        'email',
        'ad',
        'blog',
        'story',
        'smalltalk',
        'interview',
        'salespitch',
        'thanks'
    ];

    // Free account features (same as guest, just unlimited)
    const freeAccountOptions = [
        'tweet',
        'linkedin',
        'instagram',
        'youtube',
        'press',
        'casual'
    ];

    function getUserTier() {
        if (isPaid) return 'premium';
        if (isLoggedIn) return 'free';
        return 'guest';
    }

    function updateUI() {
        const counter = document.getElementById('uses-counter');
        const loginBtn = document.getElementById('login-btn');
        const registerBtn = document.getElementById('register-btn');
        const logoutBtn = document.getElementById('logout-btn');
        const upgradeBtn = document.getElementById('upgrade-btn');
        const remixBtn = document.getElementById('remix-btn');
        
        userTier = getUserTier();

        if (isPaid) {
            // Premium user
            loginBtn.classList.add('hidden');
            registerBtn.classList.add('hidden');
            logoutBtn.classList.remove('hidden');
            upgradeBtn.classList.add('hidden');
            counter.textContent = '⭐ Premium - Unlimited remixes!';
            counter.className = 'font-semibold bg-gradient-to-r from-yellow-400 to-orange-500 backdrop-blur-sm rounded-full px-6 py-2';
            remixBtn.disabled = false;
            remixBtn.textContent = '✨ Remix It Now';
        } else if (isLoggedIn) {
            // Free account user
            loginBtn.classList.add('hidden');
            registerBtn.classList.add('hidden');
            logoutBtn.classList.remove('hidden');
            upgradeBtn.classList.remove('hidden');
            counter.textContent = '🎉 Free Account - Unlimited basic remixes!';
            counter.className = 'font-semibold bg-green-500/80 backdrop-blur-sm rounded-full px-6 py-2';
            remixBtn.disabled = false;
            remixBtn.textContent = '✨ Remix It Now';
        } else {
            // Guest user
            loginBtn.classList.remove('hidden');
            registerBtn.classList.remove('hidden');
            logoutBtn.classList.add('hidden');
            upgradeBtn.classList.add('hidden');
            counter.textContent = `🆓 Guest - ${guestUsesLeft} remixes left`;
            counter.className = 'font-semibold bg-white/20 backdrop-blur-sm rounded-full px-6 py-2';
            remixBtn.disabled = false;
            remixBtn.textContent = '✨ Remix It Now';
        }
    }

    function showError(message) {
        const output = document.getElementById('output-text');
        output.textContent = `❌ Error: ${message}`;
        document.getElementById('copy-btn').classList.add('hidden');
    }

    function getGuestUsesLeft() {
        const stored = localStorage.getItem('guestUsesLeft');
        return stored ? parseInt(stored) : 3;
    }

    function setGuestUsesLeft(uses) {
        localStorage.setItem('guestUsesLeft', uses.toString());
        guestUsesLeft = uses;
    }

    async function checkSession() {
        try {
            const response = await fetch(`${API_BASE_URL}/check_session`, {
                method: 'GET',
                credentials: 'include',
                headers: {
                    'Content-Type': 'application/json'
                }
            });
            const data = await response.json();
            isLoggedIn = data.logged_in;
            isPaid = data.is_paid || false;
            
            // Only use guest uses if not logged in
            if (!isLoggedIn) {
                guestUsesLeft = getGuestUsesLeft();
            }
            
            updateUI();
        } catch (error) {
            console.error('Session check failed:', error);
            guestUsesLeft = getGuestUsesLeft();
            updateUI();
        }
    }

    function canAccessFeature(remixType) {
        if (isPaid) {
            return { canAccess: true, reason: null };
        }
        
        if (premiumOptions.includes(remixType)) {
            return { canAccess: false, reason: 'premium_required' };
        }
        
        if (!isLoggedIn) {
            if (guestUsesLeft <= 0) {
                return { canAccess: false, reason: 'guest_limit' };
            }
            // Guests can only use basic features
            if (!freeAccountOptions.includes(remixType)) {
                return { canAccess: false, reason: 'account_required' };
            }
        }
        
        return { canAccess: true, reason: null };
    }

    document.getElementById('register-btn')?.addEventListener('click', () => {
        trackButtonClick('register');
    });

    document.getElementById('upgrade-btn')?.addEventListener('click', () => {
        trackButtonClick('upgrade_button');
        trackPaywallShown('upgrade_button');
        document.getElementById('paywall').classList.remove('hidden');
    });

    document.getElementById('upgrade-cta-btn')?.addEventListener('click', () => {
        trackButtonClick('upgrade_cta');
        trackPaywallShown('upgrade_cta');
        document.getElementById('paywall').classList.remove('hidden');
    });

    document.getElementById('remix-btn').addEventListener('click', async () => {
        trackButtonClick('remix');
        const remixBtn = document.getElementById('remix-btn');
        const inputText = document.getElementById('input-text').value.trim();
        const remixType = document.getElementById('remix-type').value;
        
        if (!inputText) {
            showError('Please enter some text to remix!');
            return;
        }

        // Check feature access
        const accessCheck = canAccessFeature(remixType);
        if (!accessCheck.canAccess) {
            if (accessCheck.reason === 'premium_required') {
                trackPaywallShown('premium_feature');
                document.getElementById('paywall').classList.remove('hidden');
            } else if (accessCheck.reason === 'guest_limit') {
                trackPaywallShown('guest_limit');
                document.getElementById('guest-limit-modal').classList.remove('hidden');
            } else if (accessCheck.reason === 'account_required') {
                trackPaywallShown('account_required');
                document.getElementById('guest-limit-modal').classList.remove('hidden');
            }
            return;
        }

        remixBtn.disabled = true;
        remixBtn.innerHTML = '⏳ Remixing... (up to 2 min)';
        document.getElementById('output-text').textContent = '🤖 AI is working its magic...';

        try {
            const response = await fetch(`${API_BASE_URL}/remix`, {
                method: 'POST',
                credentials: 'include',
                headers: { 
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ 
                    prompt: inputText, 
                    'remix-type': remixType,
                    is_guest: !isLoggedIn
                })
            });

            const data = await response.json();

            if (response.ok && data.output) {
                trackRemix(remixType, userTier);
                document.getElementById('output-text').textContent = data.output;
                document.getElementById('copy-btn').classList.remove('hidden');
                
                // Update guest uses if not logged in
                if (!isLoggedIn) {
                    guestUsesLeft = Math.max(0, guestUsesLeft - 1);
                    setGuestUsesLeft(guestUsesLeft);
                    
                    if (guestUsesLeft <= 0) {
                        trackPaywallShown('guest_limit_reached');
                        setTimeout(() => {
                            document.getElementById('guest-limit-modal').classList.remove('hidden');
                        }, 1000);
                    }
                }
                
                checkSession();
            } else {
                if (data.requiresPremium) {
                    trackPaywallShown('premium_required_backend');
                    document.getElementById('paywall').classList.remove('hidden');
                } else if (data.error && data.error.includes('log in')) {
                    trackPaywallShown('login_required');
                    document.getElementById('guest-limit-modal').classList.remove('hidden');
                } else {
                    showError(data.error || 'Something went wrong!');
                }
            }
        } catch (error) {
            showError('Connection error. Please try again.');
            console.error('Remix error:', error);
        } finally {
            remixBtn.disabled = false;
            remixBtn.innerHTML = '✨ Remix It Now';
        }
    });

    document.getElementById('copy-btn').addEventListener('click', async () => {
        trackButtonClick('copy');
        const text = document.getElementById('output-text').textContent;
        try {
            await navigator.clipboard.writeText(text);
            const btn = document.getElementById('copy-btn');
            const originalText = btn.textContent;
            btn.textContent = '✅ Copied!';
            btn.style.backgroundColor = '#10b981';
            setTimeout(() => {
                btn.textContent = originalText;
                btn.style.backgroundColor = '';
            }, 2000);
        } catch (err) {
            alert('Failed to copy. Please select and copy manually.');
        }
    });

    document.getElementById('login-btn').addEventListener('click', () => {
        trackButtonClick('login');
        document.getElementById('login-modal').classList.remove('hidden');
        document.getElementById('login-error').classList.add('hidden');
    });

    document.getElementById('close-login-btn').addEventListener('click', () => {
        trackButtonClick('close_login');
        document.getElementById('login-modal').classList.add('hidden');
    });

    document.getElementById('login-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const formData = new FormData(e.target);
        const hcaptchaResponse = document.querySelector('textarea[name="h-captcha-response"]')?.value;

        try {
            const response = await fetch(`${API_BASE_URL}/login`, {
                method: 'POST',
                credentials: 'include',
                body: new URLSearchParams({
                    ...Object.fromEntries(formData),
                    'h-captcha-response': hcaptchaResponse
                })
            });

            const data = await response.json();

            if (response.ok) {
                trackLogin();
                isLoggedIn = true;
                isPaid = data.is_paid;
                document.getElementById('login-modal').classList.add('hidden');
                updateUI();
                alert('Login successful! 🎉');
            } else {
                document.getElementById('login-error').textContent = data.error || 'Login failed';
                document.getElementById('login-error').classList.remove('hidden');
            }
        } catch (error) {
            console.error('Login error:', error);
            document.getElementById('login-error').textContent = 'Failed to connect to server';
            document.getElementById('login-error').classList.remove('hidden');
        }
    });

    document.getElementById('logout-btn').addEventListener('click', async () => {
        trackButtonClick('logout');
        try {
            await fetch(`${API_BASE_URL}/logout`, {
                method: 'GET',
                credentials: 'include'
            });
            isLoggedIn = false;
            isPaid = false;
            guestUsesLeft = getGuestUsesLeft();
            updateUI();
            alert('Logged out successfully');
        } catch (error) {
            console.error('Logout error:', error);
        }
    });

    document.getElementById('contact-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const formData = new FormData(e.target);
        const status = document.getElementById('contact-status');

        try {
            const response = await fetch(`${API_BASE_URL}/contact`, {
                method: 'POST',
                credentials: 'include',
                body: formData
            });

            const data = await response.json();
            if (response.ok) {
                trackContactForm();
                status.textContent = '✅ Message sent successfully!';
                status.className = 'text-center mt-4 text-green-400';
                e.target.reset();
            } else {
                status.textContent = `❌ ${data.error}`;
                status.className = 'text-center mt-4 text-red-400';
            }
        } catch (error) {
            status.textContent = '❌ Failed to send message.';
            status.className = 'text-center mt-4 text-red-400';
        }
        status.classList.remove('hidden');
    });

    document.getElementById('close-paywall-btn').addEventListener('click', () => {
        trackButtonClick('close_paywall');
        document.getElementById('paywall').classList.add('hidden');
    });

    document.getElementById('close-guest-limit-btn')?.addEventListener('click', () => {
        trackButtonClick('close_guest_limit');
        document.getElementById('guest-limit-modal').classList.add('hidden');
    });

    document.getElementById('show-premium-from-guest')?.addEventListener('click', () => {
        trackButtonClick('show_premium_from_guest');
        document.getElementById('guest-limit-modal').classList.add('hidden');
        document.getElementById('paywall').classList.remove('hidden');
    });

    if (typeof paypal !== 'undefined') {
        paypal.Buttons({
            createSubscription: function(data, actions) {
                return actions.subscription.create({
                    plan_id: 'P-5LK680852J287884DNDUFRKA'
                });
            },
            onApprove: function(data, actions) {
                trackSubscription(data.subscriptionID);
                return fetch(`${API_BASE_URL}/update_subscription`, {
                    method: 'POST',
                    credentials: 'include',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({subscriptionID: data.subscriptionID})
                }).then(() => {
                    document.getElementById('paywall').classList.add('hidden');
                    alert('Subscription activated! 🎉');
                    location.reload();
                });
            },
            onError: function(err) {
                alert('Payment error. Please try again.');
                console.error('PayPal error:', err);
            }
        }).render('#paypal-button-container');
    }

    checkSession();
    document.getElementById('input-text').focus();
    trackPageView('NextLogicAI Home');
});