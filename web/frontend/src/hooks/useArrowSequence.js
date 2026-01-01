import { useState, useEffect } from 'react';

/**
 * Хук для отслеживания секретной комбинации стрелочек
 * Комбинация: ↑ ↑ ↓ ↓ →
 */
export const useArrowSequence = (sequence, onComplete) => {
  const [currentSequence, setCurrentSequence] = useState([]);

  useEffect(() => {
    const handleKeyDown = (event) => {
      let key = null;
      
      // Определяем нажатую стрелку
      if (event.key === 'ArrowUp') key = 'ArrowUp';
      else if (event.key === 'ArrowDown') key = 'ArrowDown';
      else if (event.key === 'ArrowLeft') key = 'ArrowLeft';
      else if (event.key === 'ArrowRight') key = 'ArrowRight';
      
      // Если нажата стрелка, обрабатываем
      if (key) {
        event.preventDefault(); // Предотвращаем прокрутку страницы
        
        setCurrentSequence(prev => {
          const newSequence = [...prev, key];
          
          // Проверяем, совпадает ли текущая последовательность с нужной
          if (newSequence.length <= sequence.length) {
            // Проверяем, совпадает ли начало
            const matches = newSequence.every((k, i) => k === sequence[i]);
            
            if (matches && newSequence.length === sequence.length) {
              // Комбинация введена полностью!
              setTimeout(() => {
                onComplete();
                setCurrentSequence([]); // Сбрасываем после успеха
              }, 0);
              return [];
            } else if (!matches) {
              // Не совпадает, сбрасываем
              return [];
            }
          } else {
            // Превышена длина, сбрасываем
            return [];
          }
          
          return newSequence;
        });
      } else {
        // Если нажата не стрелка, сбрасываем последовательность
        setCurrentSequence([]);
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [sequence, onComplete]);
};










