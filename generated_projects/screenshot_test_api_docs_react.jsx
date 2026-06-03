import React, { useState } from 'react';

const GeneratedComponent = () => {
  const [isActive, setIsActive] = useState(false);

  return (
    <div className="bg-gray-100 p-4">
      <h1 className="text-2xl font-bold text-gray-800">Welcome to My App</h1>
      <p className="mt-2 text-gray-600">This is a sample UI component.</p>
      <button
        onClick={() => setIsActive(!isActive)}
        className={`mt-4 px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-700 ${
          isActive ? 'bg-green-500' : ''
        }`}
      >
        {isActive ? 'Deactivate' : 'Activate'}
      </button>
    </div>
  );
};

export default GeneratedComponent;