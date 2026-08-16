const nodemailer = require('nodemailer');

function validateContactForm(data) {
    // Basic validation logic
    if (!data.name || !data.email || !data.message) {
        throw new Error('All fields are required');
    }
}

async function sendEmail(data) {
    let transporter = nodemailer.createTransport({
        service: 'gmail',
        auth: {
            user: 'your-email@gmail.com',
            pass: 'your-password'
        }
    });

    let info = await transporter.sendMail({
        from: data.email,
        to: 'recipient@example.com',
        subject: 'Contact Form Submission',
        text: `Name: ${data.name}
Email: ${data.email}
Message: ${data.message}`
    });

    console.log('Message sent: %s', info.messageId);
}

function contactFormController(req, res) {
    try {
        validateContactForm(req.body);
        sendEmail(req.body);
        res.status(200).send('Contact form submitted successfully');
    } catch (error) {
        res.status(400).send(error.message);
    }
}

module.exports = contactFormController;