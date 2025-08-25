using System.Collections;
using System.Collections.Generic;
using UnityEngine;

public class BlockAnimation : MonoBehaviour
{
	
    // Start is called before the first frame update
    void Start()
    {
        
    }

    // Update is called once per frame
    void Update()
    {
        
    }
	
	public void updateSpriteBlockHalfwayDug(int orientation){
		Texture2D texture = null;
		texture = Resources.Load<Texture2D>("Blocks/BlockHalfwayDug" + LevelData.blockHalfwayDugFilename[(GetComponent<BlockData>().rotation, orientation)]) as Texture2D;
		GetComponent<SpriteRenderer>().sprite = Sprite.Create(
			texture,
			new Rect(0, 0, 50, 50), // section of texture to use
			new Vector2(0.5f, 0.5f), // pivot in centre
			50 // pixels per unity tile grid unit
		);
	}
	
}
