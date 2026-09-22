from flask_sqlalchemy import SQLAlchemy
db = SQLAlchemy()

class User(db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    bio = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=db.func.now())
    
    def __repr__(self):
        return f"<User {self.username}>"