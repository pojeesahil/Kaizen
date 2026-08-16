// Import necessary modules
const nodemailer = require('nodemailer');

// Function to send email
async function sendEmail(name, email, message) {
    let transporter = nodemailer.createTransport({
        service: 'gmail',
        auth: {
            user: 'your-email@gmail.com',
            pass: 'your-password'
        }
    });

    let mailOptions = {
        from: email,
        to: 'recipient-email@example.com',
        subject: 'New Contact Form Submission',
        text: `Received message from ${name} (${email}): ${message}`
    };

    try {
        await transporter.sendMail(mailOptions);
        console.log('Email sent successfully');
    } catch (error) {
        console.error('Error sending email:', error);
    }
}

// Export the function to be used in routes
module.exports = { sendEmail };